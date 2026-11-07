"""Tests for tools/release.py, which the release workflow runs.

A fake `gh` keeps GitHub state in memory, so create, retry, partial failure and
mismatched-commit scenarios run offline. A fake PyPI does the same for publication state.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("opcp_release_tool", ROOT / "tools" / "release.py")
release = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = release  # dataclasses resolve annotations through sys.modules
_spec.loader.exec_module(release)

REPO = "TwoMuchLabs/opcp"
SHA = "a" * 40
OTHER = "b" * 40


# --------------------------------------------------------------------------- fake gh

class FakeGh:
    def __init__(self, tags=None, releases=None, annotated=None):
        self.tags = dict(tags or {})          # tag -> commit sha (lightweight)
        self.annotated = dict(annotated or {})  # tag -> (tag object sha, commit sha)
        self.releases = dict(releases or {})  # tag -> {"assets": {name: content}, "notes": str, "prerelease": bool}
        self.calls: list[list[str]] = []
        self.fail_next: dict[str, str] = {}   # subcommand key -> stderr, fails once

    def _done(self, code=0, out="", err=""):
        return subprocess.CompletedProcess(["gh"], code, out, err)

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        key = " ".join(args[:2])
        if key in self.fail_next:
            return self._done(1, err=self.fail_next.pop(key))
        if args[0] == "api":
            path = args[1]
            if "/git/ref/tags/" in path:
                tag = path.rsplit("/", 1)[1]
                if tag in self.annotated:
                    return self._done(out=json.dumps({"object": {"type": "tag", "sha": self.annotated[tag][0]}}))
                if tag in self.tags:
                    return self._done(out=json.dumps({"object": {"type": "commit", "sha": self.tags[tag]}}))
                return self._done(1, err="gh: Not Found (HTTP 404)")
            if "/git/tags/" in path:
                obj = path.rsplit("/", 1)[1]
                for tag_obj, commit in self.annotated.values():
                    if tag_obj == obj:
                        return self._done(out=json.dumps({"object": {"type": "commit", "sha": commit}}))
                return self._done(1, err="gh: Not Found (HTTP 404)")
        if args[:2] == ["release", "view"]:
            rel = self.releases.get(args[2])
            if rel is None:
                return self._done(1, err="release not found")
            return self._done(out=json.dumps({"tagName": args[2], "isDraft": False,
                                              "assets": [{"name": n} for n in rel["assets"]]}))
        if args[:2] == ["release", "create"]:
            tag = args[2]
            if tag in self.releases:
                return self._done(1, err="a release with the same tag name already exists")
            files = [a for a in args[3:args.index("--repo")]]
            if "--target" in args:
                self.tags[tag] = args[args.index("--target") + 1]
            elif "--verify-tag" in args and tag not in self.tags and tag not in self.annotated:
                return self._done(1, err="tag does not exist")
            notes = Path(args[args.index("--notes-file") + 1]).read_text()
            self.releases[tag] = {"assets": {Path(f).name: Path(f).read_bytes() for f in files},
                                  "notes": notes, "prerelease": "--prerelease" in args}
            return self._done()
        if args[:2] == ["release", "upload"]:
            tag = args[2]
            files = args[3:args.index("--repo")]
            rel = self.releases[tag]
            for f in files:
                if Path(f).name in rel["assets"] and "--clobber" not in args:
                    return self._done(1, err="asset already exists")
                rel["assets"][Path(f).name] = Path(f).read_bytes()
            return self._done()
        if args[:2] == ["release", "edit"]:
            self.releases[args[2]]["notes"] = Path(args[args.index("--notes-file") + 1]).read_text()
            return self._done()
        raise AssertionError(f"unexpected gh call {args}")


@pytest.fixture
def assets(tmp_path):
    d = tmp_path / "assets"
    d.mkdir()
    for name in ("opcp-0.3.0-py3-none-any.whl", "opcp-0.3.0.tar.gz", "opcp-exit-readiness-form-0.3.0.html"):
        (d / name).write_bytes(name.encode() + b" v2")
    notes = tmp_path / "v0.3.0.md"
    notes.write_text("release notes from the repository")
    return sorted(d.iterdir()), notes


def _release(gh, assets, **kw):
    files, notes = assets
    params = dict(repo=REPO, tag="v0.3.0", sha=SHA, assets=files, notes=notes, prerelease=True, run=gh)
    params.update(kw)
    return release.github_release(**params)


# --------------------------------------------------------------------------- GitHub release

def test_creates_release_and_tag_when_neither_exists(assets):
    # Guarantee: a first run creates the tag at the built commit and the release with all assets.
    gh = FakeGh()
    out = _release(gh, assets)
    assert out.action == "created"
    assert gh.tags["v0.3.0"] == SHA
    assert set(gh.releases["v0.3.0"]["assets"]) == {p.name for p in assets[0]}
    assert gh.releases["v0.3.0"]["prerelease"] is True


def test_creates_release_for_existing_tag_without_moving_it(assets):
    # Guarantee: when a pushed tag exists, the release is attached to it, never re-targeted.
    gh = FakeGh(tags={"v0.3.0": SHA})
    _release(gh, assets)
    create = next(c for c in gh.calls if c[:2] == ["release", "create"])
    assert "--verify-tag" in create and "--target" not in create
    assert gh.tags["v0.3.0"] == SHA


def test_rerun_after_release_exists_refreshes_assets_instead_of_failing(assets):
    # Guarantee: the failure seen on the v0.3.0 run (release already exists) cannot recur.
    gh = FakeGh(tags={"v0.3.0": SHA},
                releases={"v0.3.0": {"assets": {"opcp-0.3.0.tar.gz": b"old"}, "notes": "edited on GitHub",
                                     "prerelease": True}})
    out = _release(gh, assets)
    assert out.action == "refreshed"
    assert not any(c[:2] == ["release", "create"] for c in gh.calls)
    assert gh.releases["v0.3.0"]["assets"]["opcp-0.3.0.tar.gz"] == b"opcp-0.3.0.tar.gz v2"


def test_rerun_preserves_existing_notes_by_default(assets):
    # Guarantee: notes edited on GitHub after the first run are not silently overwritten.
    gh = FakeGh(tags={"v0.3.0": SHA},
                releases={"v0.3.0": {"assets": {}, "notes": "edited on GitHub", "prerelease": True}})
    _release(gh, assets)
    assert gh.releases["v0.3.0"]["notes"] == "edited on GitHub"


def test_rerun_can_replace_notes_when_asked(assets):
    gh = FakeGh(tags={"v0.3.0": SHA},
                releases={"v0.3.0": {"assets": {}, "notes": "old", "prerelease": True}})
    out = _release(gh, assets, update_notes=True)
    assert out.notes_updated
    assert gh.releases["v0.3.0"]["notes"] == "release notes from the repository"


def test_reports_stale_assets_without_deleting_them(assets):
    # Guarantee: refreshing never deletes a file someone may already link to.
    gh = FakeGh(tags={"v0.3.0": SHA},
                releases={"v0.3.0": {"assets": {"extra-checksums.txt": b"x"}, "notes": "", "prerelease": True}})
    out = _release(gh, assets)
    assert out.stale == ["extra-checksums.txt"]
    assert "extra-checksums.txt" in gh.releases["v0.3.0"]["assets"]


def test_refuses_assets_built_from_a_different_commit_than_the_tag(assets):
    # Guarantee: a release never carries files built from a commit other than its tag.
    gh = FakeGh(tags={"v0.3.0": OTHER})
    with pytest.raises(release.ReleaseError, match="points to"):
        _release(gh, assets)
    assert not any(c[0] == "release" and c[1] in {"create", "upload"} for c in gh.calls)


def test_annotated_tags_are_peeled_to_their_commit(assets):
    gh = FakeGh(annotated={"v0.3.0": ("c" * 40, SHA)})
    assert _release(gh, assets).action == "created"
    gh = FakeGh(annotated={"v0.3.0": ("c" * 40, OTHER)})
    with pytest.raises(release.ReleaseError):
        _release(gh, assets)


def test_partial_upload_failure_then_retry_completes(assets):
    # Guarantee: an interrupted refresh leaves a state that a plain re-run repairs.
    gh = FakeGh(tags={"v0.3.0": SHA},
                releases={"v0.3.0": {"assets": {}, "notes": "", "prerelease": True}})
    gh.fail_next["release upload"] = "HTTP 502: upstream error"
    with pytest.raises(release.ReleaseError, match="Re-running is safe"):
        _release(gh, assets)
    out = _release(gh, assets)
    assert out.action == "refreshed"
    assert set(gh.releases["v0.3.0"]["assets"]) == {p.name for p in assets[0]}


def test_create_failure_then_retry_creates(assets):
    gh = FakeGh()
    gh.fail_next["release create"] = "HTTP 500"
    with pytest.raises(release.ReleaseError):
        _release(gh, assets)
    assert _release(gh, assets).action == "created"


def test_draft_release_without_tag_is_not_guessed_at(assets):
    gh = FakeGh(releases={"v0.3.0": {"assets": {}, "notes": "", "prerelease": True}})
    with pytest.raises(release.ReleaseError, match="draft"):
        _release(gh, assets)


def test_unexpected_gh_error_is_not_treated_as_missing(assets):
    # Guarantee: an auth or network error never looks like "no release", which would
    # lead to a create attempt against an existing release.
    gh = FakeGh(tags={"v0.3.0": SHA})
    gh.fail_next["release view"] = "HTTP 401: Bad credentials"
    with pytest.raises(release.ReleaseError, match="Bad credentials"):
        _release(gh, assets)


# --------------------------------------------------------------------------- preflight

def _project(tmp_path, *, version="0.3.0", module=None, notes=True, changelog=True):
    (tmp_path / "opcp").mkdir()
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "opcp"\nversion = "{version}"\n\n[tool.x]\nversion = "9"\n')
    (tmp_path / "opcp" / "__init__.py").write_text(f'__version__ = "{module or version}"\n')
    (tmp_path / "docs" / "releases").mkdir(parents=True)
    if notes:
        (tmp_path / "docs" / "releases" / f"v{version}.md").write_text("notes")
    (tmp_path / "CHANGELOG.md").write_text(f"# Changelog\n\n## {version} (draft)\n" if changelog else "# Changelog\n")
    return tmp_path


def test_preflight_accepts_a_consistent_release(tmp_path):
    out = release.preflight("v0.3.0", _project(tmp_path))
    assert out == {"version": "0.3.0", "notes": "docs/releases/v0.3.0.md"}


@pytest.mark.parametrize("tag,kw,match", [
    ("0.3.0", {}, "not of the form"),
    ("v0.3", {}, "not of the form"),
    ("v0.3.1", {}, "does not match pyproject"),
    ("v0.3.0", {"module": "0.2.0"}, "__init__"),
    ("v0.3.0", {"notes": False}, "release notes"),
    ("v0.3.0", {"changelog": False}, "CHANGELOG"),
])
def test_preflight_rejects_inconsistent_releases_before_anything_is_built(tmp_path, tag, kw, match):
    # Guarantee: missing notes or a version mismatch stop the run before PyPI, not after it.
    with pytest.raises(release.ReleaseError, match=match):
        release.preflight(tag, _project(tmp_path, **kw))


def test_preflight_passes_on_this_repository():
    version = release.read_pyproject_version()
    assert release.preflight(f"v{version}")["version"] == version


# --------------------------------------------------------------------------- PyPI

def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_pypi_status_distinguishes_missing_from_unreachable():
    assert release.pypi_files("opcp", "9.9.9", fetch=lambda url: None) == {}

    def boom(url):
        raise OSError("network unreachable")
    with pytest.raises(OSError):
        release.pypi_files("opcp", "0.3.0", fetch=boom)


def test_reconcile_replaces_a_differing_local_build_with_the_pypi_file(tmp_path):
    # Guarantee: once a version is on PyPI, every channel ships the PyPI bytes.
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "opcp-0.3.0-py3-none-any.whl").write_bytes(b"rebuilt, different")
    (dist / "opcp-0.3.0.tar.gz").write_bytes(b"sdist")
    published = {
        "opcp-0.3.0-py3-none-any.whl": {"sha256": _digest(b"from pypi"), "url": "u1"},
        "opcp-0.3.0.tar.gz": {"sha256": _digest(b"sdist"), "url": "u2"},
    }
    fetched = []

    def fetch_file(url, dest):
        fetched.append(url)
        dest.write_bytes(b"from pypi")
    replaced = release.reconcile_dist(dist, published, fetch_file)
    assert replaced == ["opcp-0.3.0-py3-none-any.whl"]
    assert fetched == ["u1"]
    assert (dist / "opcp-0.3.0-py3-none-any.whl").read_bytes() == b"from pypi"


def test_reconcile_rejects_a_download_that_does_not_match_pypi(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "a.whl").write_bytes(b"local")
    published = {"a.whl": {"sha256": _digest(b"expected"), "url": "u"}}
    with pytest.raises(release.ReleaseError, match="digest"):
        release.reconcile_dist(dist, published, lambda url, dest: dest.write_bytes(b"tampered"))
    assert (dist / "a.whl").read_bytes() == b"local"


def test_reconcile_refuses_files_that_were_never_on_pypi(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "a.whl").write_bytes(b"x")
    (dist / "new-platform.whl").write_bytes(b"y")
    with pytest.raises(release.ReleaseError, match="not on PyPI"):
        release.reconcile_dist(dist, {"a.whl": {"sha256": _digest(b"x"), "url": "u"}}, lambda u, d: None)


def test_reconcile_is_a_no_op_before_first_publication(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "a.whl").write_bytes(b"x")
    assert release.reconcile_dist(dist, {}, lambda u, d: None) == []


# --------------------------------------------------------------------------- workflow shape

def test_workflow_publishes_to_pypi_last_and_only_when_not_already_published():
    # Guarantee: the irreversible step cannot run before the reversible ones succeed,
    # and never attempts to re-upload an existing version.
    yaml = pytest.importorskip("yaml")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    jobs = wf["jobs"]
    assert set(jobs["pypi"]["needs"]) >= {"prepare", "build", "github-release"}
    assert "pypi_exists != 'true'" in jobs["pypi"]["if"]
    assert wf["concurrency"]["cancel-in-progress"] is False
    for job in ("build", "github-release"):
        refs = [s.get("with", {}).get("ref") for s in jobs[job]["steps"] if "checkout" in str(s.get("uses", ""))]
        assert refs == ["${{ needs.prepare.outputs.sha }}"], job

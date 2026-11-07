"""Release workflow helpers (tools/release/release.py): idempotency, retries and immutability.

Each test names the release guarantee it checks. GitHub and PyPI are simulated; nothing here
touches the network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("opcp_release_tool", ROOT / "tools" / "release" / "release.py")
release = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = release
_spec.loader.exec_module(release)

SHA = "a" * 40
OTHER = "b" * 40
REPO = "TwoMuchLabs/opcp"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeGitHub:
    """Enough of the GitHub API, through `gh` arguments, to exercise every release path."""

    def __init__(self, tags=None, releases=None, fail_uploads=0, fail_create_with=None):
        self.tags = dict(tags or {})              # tag -> ("commit", sha) or ("tag", annotated sha, commit)
        self.releases = dict(releases or {})      # tag -> {"body": str, "assets": {name: bytes|None}}
        self.fail_uploads = fail_uploads
        self.fail_create_with = fail_create_with  # simulate a concurrent create
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(list(args))
        if args[0] == "api":
            return self._api(args[1])
        if args[:2] == ["release", "create"]:
            return self._create(args)
        if args[:2] == ["release", "upload"]:
            return self._upload(args)
        raise AssertionError(f"unexpected gh call {args}")

    def _api(self, path):
        prefix = f"repos/{REPO}/"
        assert path.startswith(prefix)
        path = path[len(prefix):]
        if path.startswith("git/ref/tags/"):
            tag = self.tags.get(path.rsplit("/", 1)[1])
            if tag is None:
                return release.Completed(1, "", "gh: Not Found (HTTP 404)")
            return release.Completed(0, json.dumps({"object": {"type": tag[0], "sha": tag[1]}}))
        if path.startswith("git/tags/"):
            annotated = path.rsplit("/", 1)[1]
            commit = next(t[2] for t in self.tags.values() if t[0] == "tag" and t[1] == annotated)
            return release.Completed(0, json.dumps({"object": {"type": "commit", "sha": commit}}))
        if path.startswith("releases/tags/"):
            rel = self.releases.get(path.rsplit("/", 1)[1])
            if rel is None:
                return release.Completed(1, "", "gh: Not Found (HTTP 404)")
            assets = [{"name": n, "digest": (f"sha256:{digest(b)}" if b is not None else None)}
                      for n, b in rel["assets"].items()]
            return release.Completed(0, json.dumps({"body": rel["body"], "assets": assets}))
        raise AssertionError(path)

    def _create(self, args):
        tag = args[2]
        if self.fail_create_with is not None:
            self.releases[tag] = self.fail_create_with
            self.fail_create_with = None
            return release.Completed(1, "", "HTTP 422: Validation Failed (already_exists)")
        files = [Path(a) for a in args[3:args.index("--repo")]]
        target = args[args.index("--target") + 1]
        notes = Path(args[args.index("--notes-file") + 1]).read_text(encoding="utf-8")
        self.tags.setdefault(tag, ("commit", target))
        self.releases[tag] = {"body": notes, "assets": {f.name: f.read_bytes() for f in files},
                              "prerelease": "--prerelease" in args}
        return release.Completed(0)

    def _upload(self, args):
        if self.fail_uploads:
            self.fail_uploads -= 1
            return release.Completed(1, "", "connection reset")
        tag, file = args[2], Path(args[3])
        assets = self.releases[tag]["assets"]
        if file.name in assets and "--clobber" not in args:
            return release.Completed(1, "", "asset already exists")
        assets[file.name] = file.read_bytes()
        return release.Completed(0)

    def uploads(self):
        return [Path(c[3]).name for c in self.calls if c[:2] == ["release", "upload"]]


@pytest.fixture
def built(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    files = {
        "opcp-9.9.9-py3-none-any.whl": b"wheel",
        "opcp-9.9.9.tar.gz": b"sdist",
        "opcp-example-report-9.9.9.html": b"<report>",
        "opcp-exit-readiness-form-9.9.9.html": b"<form>",
    }
    for name, data in files.items():
        (assets / name).write_bytes(data)
    notes = tmp_path / "v9.9.9.md"
    notes.write_text("Release notes\n", encoding="utf-8")
    return assets, notes, files


def publish(gh, assets, notes, **kw):
    return release.github_release(release.GitHub(REPO, gh), tag="v9.9.9", target=kw.pop("target", SHA),
                                  notes=notes, assets=assets, prerelease=kw.pop("prerelease", True), **kw)


# ---------------------------------------------------------------- tag validation


def test_tag_must_match_package_version():
    """Guarantee: a release is only ever built for the version the package declares."""
    assert release.check_tag("v0.3.0", "0.3.0") == "0.3.0"
    assert release.check_tag("v1.0.0rc1", "1.0.0rc1") == "1.0.0rc1"
    with pytest.raises(release.ReleaseError, match="does not match"):
        release.check_tag("v0.3.1", "0.3.0")
    for bad in ("0.3.0", "v0.3", "v0.3.0-final", "release-0.3.0"):
        with pytest.raises(release.ReleaseError, match="not of the form"):
            release.check_tag(bad, "0.3.0")


def test_check_tag_reads_this_repository():
    """Guarantee: the check uses the real pyproject.toml version (read without tomllib, so it works on 3.10)."""
    version = release.project_version(ROOT / "pyproject.toml")
    assert version == release._read_version(ROOT / "opcp" / "__init__.py", r'^__version__\s*=\s*"([^"]+)"')
    assert release.check_tag(f"v{version}", version) == version


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "opcp").mkdir()
    (tmp_path / "docs" / "releases").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[build-system]\nrequires = []\n\n[project]\nname = "opcp"\nversion = "9.9.9"\n\n[tool.x]\nversion = "1"\n')
    (tmp_path / "opcp" / "__init__.py").write_text('__version__ = "9.9.9"\n')
    (tmp_path / "docs" / "releases" / "v9.9.9.md").write_text("Notes\n")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 9.9.9 (draft)\n\n- x\n")
    return tmp_path


def test_preflight_passes_a_complete_release(repo):
    """Guarantee: a release whose versions, notes and changelog agree passes before anything is built."""
    assert release.preflight("v9.9.9", repo) == "9.9.9"


@pytest.mark.parametrize("breakage, message", [
    (lambda r: (r / "opcp" / "__init__.py").write_text('__version__ = "9.9.8"\n'), "opcp/__init__.py says 9.9.8"),
    (lambda r: (r / "docs" / "releases" / "v9.9.9.md").unlink(), "release notes"),
    (lambda r: (r / "docs" / "releases" / "v9.9.9.md").write_text("  \n"), "release notes"),
    (lambda r: (r / "CHANGELOG.md").write_text("# Changelog\n"), "CHANGELOG.md has no"),
    (lambda r: (r / "pyproject.toml").write_text('[project]\nname = "opcp"\nversion = "9.9.10"\n'), "does not match"),
])
def test_preflight_stops_before_building(repo, breakage, message):
    """Guarantee: a release that would ship mismatched versions or no notes stops before any build or upload."""
    breakage(repo)
    with pytest.raises(release.ReleaseError, match=message):
        release.preflight("v9.9.9", repo)


def test_new_tags_only_from_a_manual_run_on_main():
    """Guarantee: an existing tag decides the commit; a new tag is cut only from main, by a person."""
    gh = release.GitHub(REPO, FakeGitHub(tags={"v1.0.0": ("commit", OTHER)}))
    assert release.resolve(gh, "v1.0.0", SHA, "workflow_dispatch", "refs/heads/feature") == (OTHER, True)
    assert release.resolve(gh, "v9.9.9", SHA, "workflow_dispatch", "refs/heads/main") == (SHA, False)
    for event, ref in (("workflow_dispatch", "refs/heads/feature"), ("push", "refs/tags/v9.9.9")):
        with pytest.raises(release.ReleaseError, match="only by a manual run on main"):
            release.resolve(gh, "v9.9.9", SHA, event, ref)


# ---------------------------------------------------------------- GitHub release


def test_first_run_creates_release_and_tag(built):
    """Guarantee: when no release exists, one is created at the built commit with every asset and the notes."""
    assets, notes, files = built
    gh = FakeGitHub()
    plan = publish(gh, assets, notes)
    assert plan.created
    assert gh.tags["v9.9.9"] == ("commit", SHA)
    assert gh.releases["v9.9.9"]["assets"] == files
    assert gh.releases["v9.9.9"]["body"] == "Release notes\n"
    assert gh.releases["v9.9.9"]["prerelease"] is True


def test_rerun_after_success_changes_nothing(built):
    """Guarantee: re-running a completed release is a no-op (the failure seen on the v0.3.0 run)."""
    assets, notes, files = built
    gh = FakeGitHub(tags={"v9.9.9": ("commit", SHA)},
                    releases={"v9.9.9": {"body": "Release notes\n", "assets": dict(files)}})
    plan = publish(gh, assets, notes)
    assert not plan.created and gh.uploads() == []
    assert set(plan.unchanged) == set(files)
    assert not plan.notes_differ


def test_retry_after_partial_upload_fills_in_missing_assets(built):
    """Guarantee: a release interrupted mid-upload is completed by a retry, without duplicates."""
    assets, notes, files = built
    partial = {k: v for k, v in files.items() if k.endswith(".whl")}
    gh = FakeGitHub(tags={"v9.9.9": ("commit", SHA)}, releases={"v9.9.9": {"body": "Release notes\n", "assets": dict(partial)}})
    plan = publish(gh, assets, notes)
    assert sorted(plan.uploaded) == sorted(set(files) - set(partial))
    assert gh.releases["v9.9.9"]["assets"] == files


def test_upload_failure_is_reported_and_a_retry_recovers(built):
    """Guarantee: a transient upload failure stops the run with an error; the next run finishes the job."""
    assets, notes, files = built
    gh = FakeGitHub(tags={"v9.9.9": ("commit", SHA)}, releases={"v9.9.9": {"body": "Release notes\n", "assets": {}}},
                    fail_uploads=1)
    with pytest.raises(release.ReleaseError, match="could not upload"):
        publish(gh, assets, notes)
    publish(gh, assets, notes)
    assert gh.releases["v9.9.9"]["assets"] == files


def test_changed_report_is_refreshed(built):
    """Guarantee: non-distribution assets (form, example report) are refreshed when they change."""
    assets, notes, files = built
    stale = {**files, "opcp-example-report-9.9.9.html": b"<old report>"}
    gh = FakeGitHub(tags={"v9.9.9": ("commit", SHA)}, releases={"v9.9.9": {"body": "Release notes\n", "assets": stale}})
    plan = publish(gh, assets, notes)
    assert plan.replaced == ("opcp-example-report-9.9.9.html",)
    assert gh.releases["v9.9.9"]["assets"] == files


def test_changed_distribution_is_refused_and_nothing_is_touched(built):
    """Guarantee: a released wheel or sdist is never replaced; refusal happens before any upload."""
    assets, notes, files = built
    published = {**files, "opcp-9.9.9.tar.gz": b"different sdist", "opcp-example-report-9.9.9.html": b"<old>"}
    del published["opcp-exit-readiness-form-9.9.9.html"]
    gh = FakeGitHub(tags={"v9.9.9": ("commit", SHA)}, releases={"v9.9.9": {"body": "x", "assets": dict(published)}})
    with pytest.raises(release.ReleaseError, match="immutable"):
        publish(gh, assets, notes)
    assert gh.uploads() == []
    assert gh.releases["v9.9.9"]["assets"] == published


def test_distribution_without_checksum_is_left_alone(built):
    """Guarantee: a distribution whose published bytes cannot be verified is never overwritten blind."""
    assets, notes, files = built
    gh = FakeGitHub(tags={"v9.9.9": ("commit", SHA)},
                    releases={"v9.9.9": {"body": "Release notes\n", "assets": {**files, "opcp-9.9.9.tar.gz": None}}})
    plan = publish(gh, assets, notes)
    assert plan.unverified == ("opcp-9.9.9.tar.gz",)
    assert "opcp-9.9.9.tar.gz" not in gh.uploads()


def test_tag_on_another_commit_is_refused(built):
    """Guarantee: assets are only attached to a release whose tag points at the commit they were built from."""
    assets, notes, _ = built
    gh = FakeGitHub(tags={"v9.9.9": ("commit", OTHER)})
    with pytest.raises(release.ReleaseError, match="points at"):
        publish(gh, assets, notes)
    assert gh.releases == {}


def test_annotated_tag_is_dereferenced(built):
    """Guarantee: annotated tags are compared by the commit they point at, not the tag object."""
    assets, notes, _ = built
    gh = FakeGitHub(tags={"v9.9.9": ("tag", "c" * 40, SHA)})
    assert publish(gh, assets, notes).created
    gh = FakeGitHub(tags={"v9.9.9": ("tag", "c" * 40, OTHER)})
    with pytest.raises(release.ReleaseError, match="points at"):
        publish(gh, assets, notes)


def test_concurrent_create_falls_back_to_refresh(built):
    """Guarantee: if another run creates the release first, this run refreshes it instead of failing."""
    assets, notes, files = built
    gh = FakeGitHub(fail_create_with={"body": "Release notes\n", "assets": {}})
    plan = publish(gh, assets, notes)
    assert not plan.created
    assert gh.releases["v9.9.9"]["assets"] == files


def test_existing_notes_are_preserved(built):
    """Guarantee: a maintainer's edits to published notes are never overwritten; a difference is warned about."""
    assets, notes, files = built
    gh = FakeGitHub(tags={"v9.9.9": ("commit", SHA)},
                    releases={"v9.9.9": {"body": "Edited by a maintainer", "assets": dict(files)}})
    plan = publish(gh, assets, notes)
    assert plan.notes_differ
    assert gh.releases["v9.9.9"]["body"] == "Edited by a maintainer"
    assert any(line.startswith("warning") for line in plan.summary())


def test_missing_notes_or_assets_stop_the_release(built, tmp_path):
    """Guarantee: release notes and assets are required, as before."""
    assets, notes, _ = built
    with pytest.raises(release.ReleaseError, match="release notes"):
        publish(FakeGitHub(), assets, tmp_path / "missing.md")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(release.ReleaseError, match="no release assets"):
        publish(FakeGitHub(), empty, notes)


def test_other_api_errors_are_not_mistaken_for_absence(built):
    """Guarantee: an authentication or server error is a failure, not 'release does not exist'."""
    assets, notes, _ = built

    def broken(args):
        return release.Completed(1, "", "HTTP 401: Bad credentials")

    with pytest.raises(release.ReleaseError, match="Bad credentials"):
        publish(broken, assets, notes)


# ---------------------------------------------------------------- PyPI


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "opcp-9.9.9-py3-none-any.whl").write_bytes(b"wheel")
    (d / "opcp-9.9.9.tar.gz").write_bytes(b"sdist")
    return d


def pypi_with(files):
    return lambda url: {"urls": [{"filename": n, "digests": {"sha256": digest(b)}} for n, b in files.items()]}


def test_pypi_new_version_is_published(dist):
    """Guarantee: a version PyPI has never seen is uploaded."""
    publish_now, _ = release.pypi_check(dist, "opcp", "9.9.9", fetch=lambda url: None)
    assert publish_now


def test_pypi_identical_version_is_skipped(dist):
    """Guarantee: re-running after a successful upload does not try to upload again."""
    publish_now, notes = release.pypi_check(dist, "opcp", "9.9.9",
                                            fetch=pypi_with({"opcp-9.9.9-py3-none-any.whl": b"wheel", "opcp-9.9.9.tar.gz": b"sdist"}))
    assert not publish_now and "nothing to publish" in notes[0]


def test_pypi_partial_upload_publishes_the_rest(dist):
    """Guarantee: an upload interrupted after the wheel is completed by a retry."""
    publish_now, notes = release.pypi_check(dist, "opcp", "9.9.9", fetch=pypi_with({"opcp-9.9.9-py3-none-any.whl": b"wheel"}))
    assert publish_now and "opcp-9.9.9.tar.gz" in notes[1]


def test_pypi_different_bytes_are_refused(dist):
    """Guarantee: PyPI version immutability. A changed build for a published version stops the release."""
    with pytest.raises(release.ReleaseError, match="immutable"):
        release.pypi_check(dist, "opcp", "9.9.9", fetch=pypi_with({"opcp-9.9.9-py3-none-any.whl": b"other wheel"}))


def test_cli_writes_github_output(dist, tmp_path, monkeypatch, capsys):
    """Guarantee: the workflow can read the decision from $GITHUB_OUTPUT."""
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(release, "fetch_pypi", lambda url: None)
    assert release.main(["pypi-check", "--dist", str(dist), "--version", "9.9.9"]) == 0
    assert out.read_text() == "publish=true\n"
    assert release.main(["preflight", "v0.0.1", "--root", str(ROOT)]) == 1
    assert "does not match" in capsys.readouterr().err


# ---------------------------------------------------------------- adopting PyPI's bytes on retry


def make_wheel(path: Path, files: dict[str, bytes], level: int) -> Path:
    import zipfile

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=level) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def pypi_serving(files: dict[str, bytes]):
    meta = {"urls": [{"filename": n, "url": f"https://files.example/{n}", "digests": {"sha256": digest(b)}}
                     for n, b in files.items()]}
    return (lambda url: meta), (lambda url: files[url.rsplit("/", 1)[1]])


def test_retry_uses_pypi_bytes_when_contents_match(tmp_path):
    """Guarantee: after a PyPI upload, a retry attaches PyPI's exact bytes, even though a rebuild compresses differently."""
    content = {"opcp/__init__.py": b"__version__ = '9.9.9'\n" * 20}
    local = make_wheel(tmp_path / "opcp-9.9.9-py3-none-any.whl", content, level=1)
    (tmp_path / "pypi").mkdir()
    remote = make_wheel(tmp_path / "pypi" / "remote.whl", content, level=9).read_bytes()
    assert local.read_bytes() != remote
    fetch, get = pypi_serving({local.name: remote})
    notes = release.adopt_pypi(tmp_path, "opcp", "9.9.9", fetch=fetch, get=get)
    assert local.read_bytes() == remote and "using PyPI's bytes" in notes[0]
    assert not list(tmp_path.glob(".pypi-*"))
    assert release.pypi_check(tmp_path, "opcp", "9.9.9", fetch=fetch)[0] is False


def test_retry_refuses_when_pypi_contents_differ(tmp_path):
    """Guarantee: if PyPI holds different code for this version (e.g. the tag moved), the release stops."""
    local = make_wheel(tmp_path / "opcp-9.9.9-py3-none-any.whl", {"opcp/a.py": b"new"}, level=6)
    before = local.read_bytes()
    fetch, get = pypi_serving({local.name: make_wheel(tmp_path / "r.whl", {"opcp/a.py": b"old"}, 6).read_bytes()})
    with pytest.raises(release.ReleaseError, match="does not contain what this commit builds"):
        release.adopt_pypi(tmp_path, "opcp", "9.9.9", fetch=fetch, get=get)
    assert local.read_bytes() == before


def test_adopt_checks_download_integrity_and_scope(tmp_path):
    """Guarantee: a corrupted download, or a PyPI file this run did not build, is an error."""
    local = make_wheel(tmp_path / "opcp-9.9.9-py3-none-any.whl", {"a": b"x"}, 6)
    meta = {"urls": [{"filename": local.name, "url": "u/x", "digests": {"sha256": "0" * 64}}]}
    with pytest.raises(release.ReleaseError, match="checksum"):
        release.adopt_pypi(tmp_path, "opcp", "9.9.9", fetch=lambda u: meta, get=lambda u: b"tampered")
    meta = {"urls": [{"filename": "opcp-9.9.9-cp312-none-any.whl", "url": "u/y", "digests": {"sha256": "0" * 64}}]}
    with pytest.raises(release.ReleaseError, match="did not build"):
        release.adopt_pypi(tmp_path, "opcp", "9.9.9", fetch=lambda u: meta, get=lambda u: b"")
    assert "not on PyPI" in release.adopt_pypi(tmp_path, "opcp", "9.9.9", fetch=lambda u: None)[0]


def test_sdist_contents_ignore_timestamps(tmp_path):
    """Guarantee: source archives are compared by file contents, not tar metadata."""
    import io
    import tarfile

    def sdist(path, mtime):
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo("opcp-9.9.9/PKG-INFO")
            info.size, info.mtime = 3, mtime
            archive.addfile(info, io.BytesIO(b"abc"))
        return path

    a, b = sdist(tmp_path / "a.tar.gz", 0), sdist(tmp_path / "b.tar.gz", 10**9)
    assert a.read_bytes() != b.read_bytes()
    assert release.archive_contents(a) == release.archive_contents(b)


# ---------------------------------------------------------------- the workflow itself


def test_workflow_order_and_tooling_source():
    """Guarantees: PyPI (irreversible) runs only after the GitHub release succeeds; preflight runs before the
    build; and every job runs the release tooling from the workflow's own commit, so old tags can be re-released."""
    import yaml

    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    jobs = wf["jobs"]
    assert "github-release" in jobs["pypi"]["needs"]
    build = [s.get("name", "") + s.get("run", "") for s in jobs["build"]["steps"]]
    assert next(i for i, s in enumerate(build) if "preflight" in s) < next(i for i, s in enumerate(build) if "python -m build" in s)
    assert "release-tools/tools/release/release.py" in wf["env"]["TOOL"]
    for name, job in jobs.items():
        runs = " ".join(s.get("run", "") for s in job["steps"])
        assert "tools/release" not in runs.replace('"$TOOL"', ""), f"{name} runs tooling from the release source"
        if '"$TOOL"' in runs:
            tool_checkouts = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout")
                              and s.get("with", {}).get("path") == "release-tools"]
            assert tool_checkouts and "ref" not in tool_checkouts[0]["with"], name
    assert wf["concurrency"]["cancel-in-progress"] is False

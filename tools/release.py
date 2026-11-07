"""Release helpers used by .github/workflows/release.yml.

Kept outside the `opcp` package: this is project tooling, not part of the reference
runtime, and it is the only code in the repository that talks to PyPI or GitHub.

Subcommands
-----------
preflight       Validate the tag, versions, changelog and release notes before anything
                is built or published. Fails fast, so a bad release never reaches PyPI.
pypi-status     Report whether the version is already on PyPI, and the published digests.
reconcile-dist  If the version is on PyPI, make the local dist/ match PyPI exactly.
github-release  Create the GitHub release, or refresh its assets if it already exists.

Every subcommand is safe to re-run. Outputs are written as `key=value` lines to the file
named by $GITHUB_OUTPUT when set, and to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.post\d+)?)$")
PYPI_JSON = "https://pypi.org/pypi/{project}/{version}/json"


class ReleaseError(Exception):
    """A condition that must stop the release."""


# --------------------------------------------------------------------------- outputs

def emit(**values: object) -> None:
    lines = [f"{k}={'true' if v is True else 'false' if v is False else v}" for k, v in values.items()]
    for line in lines:
        print(line)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def notice(kind: str, message: str) -> None:
    """Print a GitHub Actions annotation (kind: notice, warning or error)."""
    print(f"::{kind}::{message}", file=sys.stderr if kind == "error" else sys.stdout)


# --------------------------------------------------------------------------- preflight

def read_pyproject_version(root: Path = ROOT) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    project = text.split("[project]", 1)[1].split("\n[", 1)[0]
    m = re.search(r'^version\s*=\s*"([^"]+)"', project, re.M)
    if not m:
        raise ReleaseError("pyproject.toml has no [project] version")
    return m.group(1)


def read_module_version(root: Path = ROOT) -> str:
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', (root / "opcp" / "__init__.py").read_text(encoding="utf-8"), re.M)
    if not m:
        raise ReleaseError("opcp/__init__.py has no __version__")
    return m.group(1)


def preflight(tag: str, root: Path = ROOT) -> dict[str, str]:
    """Check everything that can be checked before building. Returns version and notes path."""
    m = TAG_RE.match(tag)
    if not m:
        raise ReleaseError(f"Tag {tag!r} is not of the form vX.Y.Z (optionally aN, bN, rcN, .postN)")
    tag_version = m.group(1)
    pyproject = read_pyproject_version(root)
    module = read_module_version(root)
    if pyproject != tag_version:
        raise ReleaseError(f"Tag {tag} does not match pyproject version {pyproject}")
    if module != pyproject:
        raise ReleaseError(f"opcp/__init__.py version {module} does not match pyproject version {pyproject}")
    notes = root / "docs" / "releases" / f"{tag}.md"
    if not notes.is_file() or not notes.read_text(encoding="utf-8").strip():
        raise ReleaseError(f"Missing or empty release notes at {notes.relative_to(root)}")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## {re.escape(pyproject)}\b", changelog, re.M):
        raise ReleaseError(f"CHANGELOG.md has no '## {pyproject}' entry")
    return {"version": pyproject, "notes": str(notes.relative_to(root))}


# --------------------------------------------------------------------------- PyPI

Fetch = Callable[[str], "dict | None"]


def fetch_json(url: str) -> dict | None:
    """GET a PyPI JSON document. Returns None on 404; raises on any other failure."""
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "opcp-release-workflow"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https URL
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def pypi_files(project: str, version: str, fetch: Fetch = fetch_json) -> dict[str, dict[str, str]]:
    """Map filename -> {sha256, url} for a published version; empty if not published.

    A failure to reach PyPI is an error, never "not published": guessing wrong would
    either attempt a forbidden re-upload or skip a needed one.
    """
    doc = fetch(PYPI_JSON.format(project=project, version=version))
    if doc is None:
        return {}
    return {f["filename"]: {"sha256": f["digests"]["sha256"], "url": f["url"]} for f in doc.get("urls", [])}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


Download = Callable[[str, Path], None]


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "opcp-release-workflow"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:  # noqa: S310
        fh.write(resp.read())


def reconcile_dist(dist: Path, published: dict[str, dict[str, str]], fetch_file: Download = download) -> list[str]:
    """Make `dist` hold exactly the files PyPI serves for this version.

    PyPI files are immutable, so once a version is published they are the canonical
    artifacts. A local build that differs (a non-reproducible build, or a rebuild from a
    different commit) is replaced, so the GitHub release never carries a wheel that
    differs from the one `pip install` gets. Returns the names of replaced files.
    """
    if not published:
        return []
    replaced = []
    local = {p.name: p for p in dist.iterdir() if p.is_file()}
    missing_on_pypi = sorted(set(local) - set(published))
    if missing_on_pypi:
        # e.g. a new file type that was never uploaded; it cannot be added to an existing
        # PyPI release by this workflow, and shipping it only on GitHub would diverge.
        raise ReleaseError(f"Built files not on PyPI for this version: {', '.join(missing_on_pypi)}")
    for name, meta in sorted(published.items()):
        target = dist / name
        if target.exists() and sha256(target) == meta["sha256"]:
            continue
        tmp = dist / f".{name}.download"
        fetch_file(meta["url"], tmp)
        if sha256(tmp) != meta["sha256"]:
            tmp.unlink(missing_ok=True)
            raise ReleaseError(f"Downloaded {name} does not match the PyPI digest")
        tmp.replace(target)
        replaced.append(name)
    return replaced


# --------------------------------------------------------------------------- GitHub release

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def run_gh(args: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


@dataclass
class ReleaseOutcome:
    action: str  # "created" or "refreshed"
    uploaded: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    notes_updated: bool = False


def _gh_json(run: Runner, args: Sequence[str]) -> dict | None:
    res = run(args)
    if res.returncode != 0:
        err = (res.stderr or "").lower()
        if "not found" in err or "http 404" in err:
            return None
        raise ReleaseError(f"gh {' '.join(args)} failed: {res.stderr.strip()}")
    return json.loads(res.stdout)


def tag_commit(run: Runner, repo: str, tag: str) -> str | None:
    """The commit a tag points to, peeling annotated tags. None if the tag does not exist."""
    ref = _gh_json(run, ["api", f"repos/{repo}/git/ref/tags/{tag}"])
    if ref is None:
        return None
    obj = ref["object"]
    while obj["type"] == "tag":
        tag_obj = _gh_json(run, ["api", f"repos/{repo}/git/tags/{obj['sha']}"])
        if tag_obj is None:
            raise ReleaseError(f"Annotated tag object {obj['sha']} for {tag} not found")
        obj = tag_obj["object"]
    return obj["sha"]


def github_release(*, repo: str, tag: str, sha: str, assets: Sequence[Path], notes: Path,
                   prerelease: bool, update_notes: bool = False, run: Runner = run_gh) -> ReleaseOutcome:
    """Create the release, or bring an existing one's assets up to date.

    Never moves a tag and never attaches assets built from a different commit than the
    one the tag points to.
    """
    if not assets:
        raise ReleaseError("No assets to attach")
    existing_tag_sha = tag_commit(run, repo, tag)
    if existing_tag_sha is not None and existing_tag_sha != sha:
        raise ReleaseError(f"Tag {tag} points to {existing_tag_sha[:12]}, but the assets were built from "
                           f"{sha[:12]}. Refusing to attach them. Re-run the workflow for that commit.")

    release = _gh_json(run, ["release", "view", tag, "--repo", repo, "--json", "tagName,isDraft,assets"])
    names = [str(a) for a in assets]

    if release is None:
        args = ["release", "create", tag, *names, "--repo", repo, "--title", f"OPCP {tag}",
                "--notes-file", str(notes)]
        if existing_tag_sha is None:
            args += ["--target", sha]
        else:
            args += ["--verify-tag"]
        if prerelease:
            args.append("--prerelease")
        res = run(args)
        if res.returncode != 0:
            raise ReleaseError(f"Creating release {tag} failed: {res.stderr.strip()}")
        return ReleaseOutcome(action="created", uploaded=[Path(n).name for n in names])

    if existing_tag_sha is None:
        # A draft release whose tag has not been created. Its target is not verifiable
        # here, so do not guess.
        raise ReleaseError(f"Release {tag} exists but its tag does not. Publish or delete the draft first.")

    res = run(["release", "upload", tag, *names, "--repo", repo, "--clobber"])
    if res.returncode != 0:
        raise ReleaseError(f"Uploading assets to {tag} failed: {res.stderr.strip()}. Re-running is safe.")
    current = {Path(n).name for n in names}
    stale = sorted(a["name"] for a in release.get("assets", []) if a["name"] not in current)

    notes_updated = False
    if update_notes:
        res = run(["release", "edit", tag, "--repo", repo, "--notes-file", str(notes)])
        if res.returncode != 0:
            raise ReleaseError(f"Updating notes for {tag} failed: {res.stderr.strip()}")
        notes_updated = True
    return ReleaseOutcome(action="refreshed", uploaded=sorted(current), stale=stale, notes_updated=notes_updated)


# --------------------------------------------------------------------------- CLI

def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/release.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("preflight")
    p.add_argument("--tag", required=True)

    p = sub.add_parser("pypi-status")
    p.add_argument("--project", default="opcp")
    p.add_argument("--version", required=True)

    p = sub.add_parser("reconcile-dist")
    p.add_argument("--project", default="opcp")
    p.add_argument("--version", required=True)
    p.add_argument("--dist", type=Path, default=Path("dist"))

    p = sub.add_parser("github-release")
    p.add_argument("--repo", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--notes", type=Path, required=True)
    p.add_argument("--prerelease", default="true")
    p.add_argument("--update-notes", default="false")
    p.add_argument("assets", nargs="+", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "preflight":
            emit(**preflight(args.tag))
        elif args.cmd == "pypi-status":
            files = pypi_files(args.project, args.version)
            emit(pypi_exists=bool(files))
            if files:
                notice("notice", f"{args.project} {args.version} is already on PyPI "
                                 f"({', '.join(sorted(files))}). PyPI versions are immutable; it will not be re-uploaded.")
        elif args.cmd == "reconcile-dist":
            replaced = reconcile_dist(args.dist, pypi_files(args.project, args.version))
            for name in replaced:
                notice("warning", f"{name} built here differs from PyPI; using the PyPI file so all channels match.")
            emit(replaced=",".join(replaced))
        elif args.cmd == "github-release":
            outcome = github_release(repo=args.repo, tag=args.tag, sha=args.sha, assets=args.assets,
                                     notes=args.notes, prerelease=_bool(args.prerelease),
                                     update_notes=_bool(args.update_notes))
            if outcome.stale:
                notice("warning", f"Release {args.tag} has assets this run did not produce, left in place: "
                                  f"{', '.join(outcome.stale)}")
            notice("notice", f"Release {args.tag} {outcome.action}; uploaded {len(outcome.uploaded)} assets"
                             + ("; notes updated" if outcome.notes_updated else ""))
            emit(release_action=outcome.action)
    except ReleaseError as exc:
        notice("error", str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

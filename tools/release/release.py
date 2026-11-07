#!/usr/bin/env python3
"""Release helpers for the OPCP release workflow (.github/workflows/release.yml).

Every command is safe to re-run. A failed or interrupted release can be retried
from the Actions tab without manual clean-up, and a retry never changes a file
that is already public under the same version.

Commands
--------
resolve --tag T --fallback SHA
    The commit to release: the tag's commit if the tag exists, otherwise SHA
    (the tag is then created at SHA when the release is created). This is what
    keeps a re-run for an existing tag from building whatever is on main now.

check-tag TAG
    The tag must look like ``v<semver>`` and match the version in pyproject.toml.

github-release --tag T --target SHA --notes FILE --assets DIR [--prerelease]
    Creates the GitHub release if it does not exist. If it exists, the tag must
    point at SHA, and the release's assets are refreshed:
      * an asset with the same name and identical bytes is left alone;
      * a missing asset is uploaded;
      * a changed non-distribution asset (the HTML form and reports) is replaced;
      * a changed wheel or source archive is an error, because the same version
        on PyPI can never change and the two must stay identical.
    Existing release notes are never overwritten; a difference from FILE is
    reported as a warning so a maintainer can decide.

adopt-pypi --dist DIR --project NAME --version V
    If V is already on PyPI, replaces the freshly built distributions with PyPI's
    files, after checking that they contain exactly the same files with the same
    contents. Rebuilds are not byte-reproducible across machines (compression
    differs), so this is what lets a retry attach the published bytes to the
    GitHub release instead of failing.

pypi-check --dist DIR --project NAME --version V
    Compares the built distributions with what PyPI already holds for V and
    writes ``publish=true|false`` to $GITHUB_OUTPUT (or stdout):
      * V not on PyPI, or some files missing: publish=true (the upload step
        skips files that are already there);
      * every file already on PyPI with identical bytes: publish=false;
      * any file on PyPI with different bytes: error. PyPI versions are
        immutable, so a release must not try to replace them.

Only the Python standard library and the ``gh`` command-line tool are used.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

# PEP 440 subset that the project uses for tags: v1.2.3, v1.2.3rc1, v1.2.3.dev4, v1.2.3.post1
TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?)$")
DISTRIBUTION_SUFFIXES = (".whl", ".tar.gz")


class ReleaseError(RuntimeError):
    """A condition a retry cannot fix on its own; a maintainer must act."""


# ---------------------------------------------------------------- utilities


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def is_distribution(name: str) -> bool:
    return name.endswith(DISTRIBUTION_SUFFIXES)


def project_version(pyproject: Path) -> str:
    import tomllib

    with pyproject.open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def check_tag(tag: str, version: str) -> str:
    match = TAG_PATTERN.match(tag)
    if not match:
        raise ReleaseError(f"tag {tag!r} is not of the form v<major>.<minor>.<patch>")
    if match["version"] != version:
        raise ReleaseError(f"tag {tag} does not match the package version {version} in pyproject.toml")
    return version


# ---------------------------------------------------------------- GitHub


Runner = Callable[[Sequence[str]], "Completed"]


@dataclass
class Completed:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def run_gh(args: Sequence[str]) -> Completed:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    return Completed(proc.returncode, proc.stdout, proc.stderr)


def _not_found(result: Completed) -> bool:
    return result.returncode != 0 and ("404" in result.stderr or "Not Found" in result.stderr)


class GitHub:
    """The few GitHub operations a release needs, through the ``gh`` CLI."""

    def __init__(self, repo: str, runner: Runner = run_gh):
        self.repo = repo
        self.run = runner

    def _api(self, *args: str) -> Completed:
        return self.run(["api", *args])

    def _json(self, result: Completed, what: str):
        if result.returncode != 0:
            raise ReleaseError(f"could not {what}: {result.stderr.strip() or result.stdout.strip()}")
        return json.loads(result.stdout or "null")

    def tag_commit(self, tag: str) -> str | None:
        """The commit a tag points at, following an annotated tag; None if the tag does not exist."""
        result = self._api(f"repos/{self.repo}/git/ref/tags/{tag}")
        if _not_found(result):
            return None
        obj = self._json(result, f"read tag {tag}")["object"]
        if obj["type"] == "tag":  # annotated tag: dereference to the commit
            obj = self._json(self._api(f"repos/{self.repo}/git/tags/{obj['sha']}"), f"read annotated tag {tag}")["object"]
        return obj["sha"]

    def release(self, tag: str) -> dict | None:
        result = self._api(f"repos/{self.repo}/releases/tags/{tag}")
        if _not_found(result):
            return None
        return self._json(result, f"read release {tag}")

    def create(self, tag: str, target: str, title: str, notes: Path, prerelease: bool, files: Sequence[Path]) -> Completed:
        # --target only takes effect when the tag does not exist yet; github_release() has already
        # checked that an existing tag points at the same commit.
        args = ["release", "create", tag, *map(str, files), "--repo", self.repo, "--target", target,
                "--title", title, "--notes-file", str(notes)]
        if prerelease:
            args.append("--prerelease")
        return self.run(args)

    def upload(self, tag: str, file: Path, clobber: bool) -> None:
        args = ["release", "upload", tag, str(file), "--repo", self.repo]
        if clobber:
            args.append("--clobber")
        result = self.run(args)
        if result.returncode != 0:
            raise ReleaseError(f"could not upload {file.name}: {result.stderr.strip()}")


@dataclass
class Plan:
    created: bool = False
    uploaded: tuple[str, ...] = ()
    replaced: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    unverified: tuple[str, ...] = ()
    notes_differ: bool = False

    def summary(self) -> list[str]:
        lines = ["created the release" if self.created else "release already existed; refreshed its assets"]
        for label, names in (("uploaded", self.uploaded), ("replaced", self.replaced),
                             ("unchanged", self.unchanged), ("left in place (not built by this run)", self.extra)):
            if names:
                lines.append(f"{label}: {', '.join(names)}")
        if self.unverified:
            lines.append("warning: GitHub reported no checksum for " + ", ".join(self.unverified)
                         + "; left unchanged, compare them with PyPI by hand")
        if self.notes_differ:
            lines.append("warning: the published release notes differ from the notes file; they were not changed")
        return lines


def github_release(gh: GitHub, *, tag: str, target: str, notes: Path, assets: Path,
                   prerelease: bool, title: str | None = None) -> Plan:
    if not notes.is_file():
        raise ReleaseError(f"missing release notes at {notes}")
    files = sorted(p for p in assets.iterdir() if p.is_file())
    if not files:
        raise ReleaseError(f"no release assets in {assets}")

    tagged = gh.tag_commit(tag)
    if tagged is not None and tagged != target:
        raise ReleaseError(f"tag {tag} points at {tagged}, but this run built {target}; "
                           "re-run the workflow from the tag, or delete and recreate the tag deliberately")

    existing = gh.release(tag)
    if existing is None:
        result = gh.create(tag, target, title or f"OPCP {tag}", notes, prerelease, files)
        if result.returncode == 0:
            return Plan(created=True, uploaded=tuple(p.name for p in files))
        # Another run may have created it between our check and our create; fall through and refresh.
        existing = gh.release(tag)
        if existing is None:
            raise ReleaseError(f"could not create release {tag}: {result.stderr.strip()}")

    published = {a["name"]: (a.get("digest") or "").removeprefix("sha256:") for a in existing.get("assets", [])}
    plan = Plan()
    uploaded, replaced, unchanged = [], [], []
    # Check every distribution before changing anything, so a refusal leaves the release untouched.
    for path in files:
        old = published.get(path.name)
        if old and is_distribution(path.name) and old != sha256_file(path):
            raise ReleaseError(f"{path.name} on the release differs from the one just built. Released "
                               "distributions are immutable (PyPI never accepts a changed file for a version); "
                               "bump the version instead")
    unverified = []
    for path in files:
        old = published.get(path.name)
        if old is None:
            gh.upload(tag, path, clobber=False)
            uploaded.append(path.name)
        elif not old and is_distribution(path.name):
            unverified.append(path.name)  # GitHub gave no digest: never overwrite a released distribution blind
        elif not old or old != sha256_file(path):  # no digest reported, or a changed report or form
            gh.upload(tag, path, clobber=True)
            replaced.append(path.name)
        else:
            unchanged.append(path.name)
    plan.uploaded, plan.replaced, plan.unchanged = tuple(uploaded), tuple(replaced), tuple(unchanged)
    plan.unverified = tuple(unverified)
    plan.extra = tuple(sorted(set(published) - {p.name for p in files}))
    plan.notes_differ = (existing.get("body") or "").strip() != notes.read_text(encoding="utf-8").strip()
    return plan


# ---------------------------------------------------------------- PyPI


Fetch = Callable[[str], "dict | None"]


def fetch_pypi(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def archive_contents(path: Path) -> dict[str, str]:
    """Member name -> sha256 of its bytes, ignoring timestamps, permissions and compression.

    Rebuilding the same source on another machine gives a wheel with the same files but different
    archive bytes (zlib versions differ), so archives are compared by what they contain.
    """
    import tarfile
    import zipfile

    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            return {i.filename: digest_bytes(archive.read(i)) for i in archive.infolist() if not i.is_dir()}
    with tarfile.open(path, "r:gz") as archive:
        return {m.name: digest_bytes(archive.extractfile(m).read()) for m in archive.getmembers() if m.isfile()}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def adopt_pypi(dist: Path, project: str, version: str, fetch: Fetch | None = None,
               get: Callable[[str], bytes] | None = None) -> list[str]:
    """Replace freshly built distributions with the bytes PyPI already holds for this version.

    A version can be uploaded to PyPI once. When a release is retried after the upload, the rebuilt
    files usually differ byte-for-byte from the published ones, so the release must use PyPI's files,
    after checking they contain exactly what this commit builds. Returns notes for the log.
    """
    fetch, get = fetch or fetch_pypi, get or download
    data = fetch(f"https://pypi.org/pypi/{project}/{version}/json")
    if data is None:
        return [f"{project} {version} is not on PyPI; using this run's build"]
    notes = []
    for item in data.get("urls", []):
        name, expected = item["filename"], item["digests"]["sha256"]
        local = dist / name
        if not local.exists():
            raise ReleaseError(f"PyPI holds {name} for {project} {version}, which this run did not build")
        blob = get(item["url"])
        if digest_bytes(blob) != expected:
            raise ReleaseError(f"download of {name} from PyPI does not match PyPI's own checksum")
        if digest_bytes(blob) == sha256_file(local):
            notes.append(f"{name}: identical to PyPI")
            continue
        published = dist / f".pypi-{name}"
        published.write_bytes(blob)
        try:
            if archive_contents(published) != archive_contents(local):
                raise ReleaseError(f"{name} on PyPI does not contain what this commit builds. The tag may have "
                                   "moved since the upload; PyPI versions are immutable, so bump the version")
            published.replace(local)
        finally:
            published.unlink(missing_ok=True)
        notes.append(f"{name}: same contents as PyPI; using PyPI's bytes")
    return notes


def pypi_check(dist: Path, project: str, version: str, fetch: Fetch | None = None) -> tuple[bool, list[str]]:
    """Return (publish?, notes). Raises ReleaseError if PyPI holds different bytes for this version."""
    fetch = fetch or fetch_pypi
    built = {p.name: sha256_file(p) for p in sorted(dist.iterdir()) if is_distribution(p.name)}
    if not built:
        raise ReleaseError(f"no distributions in {dist}")
    data = fetch(f"https://pypi.org/pypi/{project}/{version}/json")
    if data is None:
        return True, [f"{project} {version} is not on PyPI yet"]
    remote = {u["filename"]: u["digests"]["sha256"] for u in data.get("urls", [])}
    changed = [n for n, h in built.items() if n in remote and remote[n] != h]
    if changed:
        raise ReleaseError(f"PyPI already holds {', '.join(changed)} for {project} {version} with different "
                           "contents. PyPI versions are immutable; bump the version")
    missing = [n for n in built if n not in remote]
    if missing:
        return True, [f"already on PyPI with identical contents: {', '.join(n for n in built if n in remote)}",
                      f"to upload: {', '.join(missing)}"]
    return False, [f"{project} {version} is already on PyPI with identical contents; nothing to publish"]


# ---------------------------------------------------------------- CLI


def _output(key: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"{key}={value}\n")
    print(f"{key}={value}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-tag")
    p.add_argument("tag")
    p.add_argument("--pyproject", default="pyproject.toml", type=Path)
    p = sub.add_parser("resolve")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    p.add_argument("--tag", required=True)
    p.add_argument("--fallback", required=True, help="commit to release when the tag does not exist yet")
    p = sub.add_parser("github-release")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    p.add_argument("--tag", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--notes", required=True, type=Path)
    p.add_argument("--assets", required=True, type=Path)
    p.add_argument("--title")
    p.add_argument("--prerelease", action="store_true")
    for name in ("pypi-check", "adopt-pypi"):
        p = sub.add_parser(name)
        p.add_argument("--dist", required=True, type=Path)
        p.add_argument("--project", default="opcp")
        p.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "check-tag":
            _output("version", check_tag(args.tag, project_version(args.pyproject)))
        elif args.command == "resolve":
            if not args.repo:
                raise ReleaseError("--repo or GITHUB_REPOSITORY is required")
            tagged = GitHub(args.repo).tag_commit(args.tag)
            _output("tag_exists", "true" if tagged else "false")
            _output("sha", tagged or args.fallback)
        elif args.command == "adopt-pypi":
            for line in adopt_pypi(args.dist, args.project, args.version):
                print(line)
        elif args.command == "github-release":
            if not args.repo:
                raise ReleaseError("--repo or GITHUB_REPOSITORY is required")
            plan = github_release(GitHub(args.repo), tag=args.tag, target=args.target, notes=args.notes,
                                  assets=args.assets, prerelease=args.prerelease, title=args.title)
            for line in plan.summary():
                print(("::warning::" if line.startswith("warning") else "") + line)
        else:
            publish, notes = pypi_check(args.dist, args.project, args.version)
            for line in notes:
                print(line)
            _output("publish", "true" if publish else "false")
    except ReleaseError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

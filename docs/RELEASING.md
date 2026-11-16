# Releasing OPCP

Releases are built and published by GitHub Actions ([`.github/workflows/release.yml`](../.github/workflows/release.yml)), so nobody needs to build files on their own machine.

## Each release

1. Set the version in `pyproject.toml` and `opcp/__init__.py`, and add a `CHANGELOG.md` entry.
2. Write the release notes at `docs/releases/v<version>.md`. The workflow refuses to run without them.
3. Merge to `main`.
4. Start the release, in either of two ways:
   - **From GitHub:** Actions → Release → Run workflow. Enter the tag (for example `v0.3.0`), tick or untick "pre-release", and tick "publish to PyPI" if wanted. The tag is created on `main` if it doesn't exist yet.
   - **From a terminal:** `git tag v0.3.0 && git push origin v0.3.0`. This publishes the GitHub release (as a pre-release) but not PyPI.

The workflow checks that the tag matches the package version, builds the package, runs the tests against the wheel it will release, and attaches five files to the release:

- the wheel and source archive;
- `opcp-exit-readiness-form-<version>.html`, the offline form;
- `opcp-example-report-<version>.html`, the report for the hypothetical example bank;
- `opcp-example-readout-<version>.html`, the sponsor readout for the same example.

## Re-running a release

Every part of the workflow is safe to run again for the same tag, for example after a network failure, a failed job or a partial upload. Use **Actions → Release → Run workflow** with the same tag, or **Re-run failed jobs** on the failed run.

- **It releases the tag, not today's `main`.** If the tag exists, the workflow builds the commit the tag points at. A new tag is created only by a manual run started from `main`, at the commit the run started from; any other run for a missing tag stops.
- **Checks come first.** Before building, the workflow checks that the tag, `pyproject.toml` and `opcp/__init__.py` agree, that `docs/releases/<tag>.md` exists and isn't empty, and that `CHANGELOG.md` has an entry for the version.
- **PyPI is last.** It runs only after the GitHub release succeeds, because a PyPI upload can never be undone.
- **An existing GitHub release is refreshed, not recreated.** Missing assets are uploaded and a changed form or example report is replaced. A wheel or source archive that is already attached is never replaced: if a rebuild differs from it, the run stops. Release notes already on the release are left as they are; if they differ from `docs/releases/<tag>.md`, the run warns. The pre-release setting only applies when the release is first created.
- **PyPI is never asked to change a published file.** If the version is already on PyPI, the workflow downloads PyPI's files, checks they contain exactly what the tag builds, and uses those files for the tests and the GitHub release. (Rebuilding the same source on another machine gives the same files inside the wheel but different archive bytes, so the published bytes are reused rather than rebuilt.) Only files PyPI does not yet hold are uploaded. If PyPI holds different contents for the version, the run stops: bump the version instead.
- **Runs for the same tag queue** rather than racing each other.

When a run stops with an error, it says what to do. Nothing needs cleaning up by hand before a retry.

The logic lives in [`tools/release/release.py`](../tools/release/release.py) and is tested in `tests/test_release_tooling.py`, including retries after partial uploads, a concurrent run, a moved tag and changed distributions. The workflow always uses the release tooling from the commit the workflow runs from, so an older tag can be re-released with the current tooling.

## One-off PyPI setup (trusted publishing, no passwords or tokens)

1. Sign in at [pypi.org](https://pypi.org). Turn on two-factor authentication if it isn't already on.
2. Go to **Your projects → Publishing → Add a new pending publisher** and enter:
   - PyPI project name: `opcp`
   - Owner: `TwoMuchLabs`
   - Repository: `opcp`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. In this repository: **Settings → Environments → New environment → `pypi`**. Optionally add yourself as a required reviewer, so every PyPI upload waits for a click.
4. Run the Release workflow with "publish to PyPI" ticked.

A version number can be uploaded to PyPI only once and can never be reused, even after deletion. Publish to PyPI only when the name check is done and the version is final.

When the repository moves to another owner, update the pending or trusted publisher on PyPI to the new owner. Otherwise uploads will fail.

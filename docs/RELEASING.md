# Releasing OPCP

Releases are built and published by GitHub Actions ([`.github/workflows/release.yml`](../.github/workflows/release.yml)), so nobody needs to build files on their own machine.

## Each release

1. Set the version in `pyproject.toml` and `opcp/__init__.py`, and add a `CHANGELOG.md` entry.
2. Write the release notes at `docs/releases/v<version>.md`. The workflow refuses to run without them.
3. Merge to `main`.
4. Start the release, in either of two ways:
   - **From GitHub:** Actions → Release → Run workflow, on the `main` branch. Enter the tag (for example `v0.3.0`), tick or untick "pre-release", and tick "publish to PyPI" if wanted. The tag is created on `main` if it doesn't exist yet.
   - **From a terminal:** `git tag v0.3.0 && git push origin v0.3.0`. This publishes the GitHub release (as a pre-release) but not PyPI.

The workflow runs four jobs in this order: **prepare** (checks), **build**, **github-release**, then **pypi**. Before anything is built it checks that the tag has the form `vX.Y.Z`, that it matches the version in `pyproject.toml` and `opcp/__init__.py`, that `CHANGELOG.md` has an entry and that the release notes exist. It then builds the package from the tagged commit, runs the tests against the installed wheel, and attaches five files to the release:

- the wheel and source archive;
- `opcp-exit-readiness-form-<version>.html`, the offline form;
- `opcp-example-report-<version>.html`, the report for the hypothetical example bank;
- `opcp-example-readout-<version>.html`, the sponsor readout for the same example.

## Re-running a release

Every job is safe to re-run, and PyPI is always last, so a failure never leaves PyPI ahead of GitHub.

| Situation | What a re-run does |
|---|---|
| The tag already exists | Builds from the commit the tag points to, never from the current `main`. A tag is never moved. |
| The GitHub release already exists | Replaces its assets with this run's files. Keeps the existing notes and pre-release setting, unless "update notes" is ticked. Assets the run did not produce are left in place and listed as a warning. |
| The release exists but its tag points to another commit than the one built | Stops without changing anything. |
| The version is already on PyPI | Skips the upload (PyPI versions can never be replaced) and downloads the PyPI wheel and source archive, checks them against PyPI's SHA-256 digests, and attaches those to the GitHub release, so every channel ships identical files. |
| An upload to GitHub failed part way | Run again; the release is completed. |
| Release notes are missing | Stops in the first job, before anything is built or published. |

Two runs for the same tag queue rather than race. The logic lives in [`tools/release.py`](../tools/release.py) and is tested offline in `tests/test_release_tooling.py`.

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

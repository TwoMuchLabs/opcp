# Releasing OPCP

Releases are built and published by GitHub Actions ([`.github/workflows/release.yml`](../.github/workflows/release.yml)), so nobody needs to build files on their own machine.

## Each release

1. Set the version in `pyproject.toml` and `opcp/__init__.py`, and add a `CHANGELOG.md` entry.
2. Write the release notes at `docs/releases/v<version>.md`. The workflow refuses to run without them.
3. Merge to `main`.
4. Start the release, in either of two ways:
   - **From GitHub:** Actions → Release → Run workflow. Enter the tag (for example `v0.3.0`), tick or untick "pre-release", and tick "publish to PyPI" if wanted. The tag is created on `main` if it doesn't exist yet.
   - **From a terminal:** `git tag v0.3.0 && git push origin v0.3.0`. This publishes the GitHub release (as a pre-release) but not PyPI.

The workflow checks that the tag matches the package version, builds the package, runs the tests against the built wheel, and attaches five files to the release:

- the wheel and source archive;
- `opcp-exit-readiness-form-<version>.html`, the offline form;
- `opcp-example-report-<version>.html`, the report for the hypothetical example bank;
- `opcp-example-readout-<version>.html`, the sponsor readout for the same example.

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

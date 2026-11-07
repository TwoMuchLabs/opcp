# Versioning

OPCP carries several version numbers. They answer different questions, and until now the relationship between them was not written down. This page records what each one means **today**, where they disagree, and what is still to be decided. The decision itself is a specification matter and is proposed in [ADR 0001](adr/0001-versioning-model.md) for public review.

## What each version number means today

| Marker | Where | Value on `main` | What it versions | Who should rely on it |
|---|---|---|---|---|
| Package version | `pyproject.toml`, `opcp.__version__`, release tag `v*` | `0.3.0` | The Python package: reference runtime, CLI, scorecard, bundled data | Anyone installing `opcp` from PyPI |
| Release label | `README.md` status line, release notes, CHANGELOG | "draft 0.3" | The repository release as a whole | Readers |
| Specification header | `spec/SPEC.md` | `0.2.0 (draft)` | The core specification text | Implementers |
| Swap-drill specification | `spec/SWAP-DRILL.md` title | `OPCP v0.3` | The swap-drill companion specification | Implementers |
| `opcp_version` in contracts and routes | `schema/capability.schema.json`, `schema/route.schema.json` (`const`) | `"0.1"` | Document format of contracts and routes | Anyone writing contracts or routes |
| `opcp_version` in swap-drill records | `schema/swap-drill.schema.json` (`const`) | `"0.3"` | Document format of swap-drill evidence | Anyone producing or consuming drill evidence |
| `opcp_version` in process packs | `examples/sme-credit-origination.yaml` | `"0.2"` | Provisional process-pack format (not normative; no schema) | Nobody yet |
| `envelope_version` | `schema/envelope.schema.json` (`const`), `opcp.envelope.ENVELOPE_VERSION` | `"0.1"` | Wire format of requests and responses | Adapter and runtime implementers |
| `answers_version` | `schema/answers.schema.json` (`const`) | `"0.1"` | Format of a scorecard answers file | Anyone producing answers (form, spreadsheet, API) |
| `scorecard_version` | `schema/scorecard.schema.json` (`const`) | `"0.1"` | Format of a scorecard assessment file | Anyone producing assessments |
| Schema `$id` | `urn:opcp:schema:<v>:<name>` in every schema | `0.1` for six schemas, `0.3` for swap-drill | Schema identity | Validators and tooling |
| `bank_version` | `questions/exit-readiness.yaml` | `"0.2"` | The scorecard question bank | Firms comparing assessments over time |
| `SPEC_VERSION` | `opcp/__init__.py` | `"0.1"` | Nothing: defined but not used anywhere | — |

## Findings

1. **The package version and the protocol version are already independent in practice**, and that is the right outcome. The package moved 0.1.0 → 0.2.0 → 0.3.0; contracts, routes and envelopes have stayed at `0.1` throughout because their formats did not change. Nothing in the repository said this was intended.
2. **`opcp_version` is used with two different meanings.** In contracts and routes it is the version of the document format (`0.1`). In swap-drill records it is a release label (`0.3`). Spec section 6.1 describes it as "the specification version the contract targets", which matches neither the spec header (`0.2.0`) nor the schemas.
3. **The specification header is behind the release.** `spec/SPEC.md` says `0.2.0`, while `spec/SWAP-DRILL.md`, added in the 0.3.0 release, calls itself "OPCP v0.3". An implementer cannot tell which core-specification text a "v0.3" swap drill depends on.
4. **A contract that follows section 6.1 literally fails validation.** Writing `opcp_version: "0.2"` (the spec header's version) is rejected by the schema's `const: "0.1"`.
5. **`SPEC_VERSION = "0.1"` is dead code** and disagrees with the spec header.
6. **The normative swap-drill specification and schema have not had the 14-day public review.** They arrived through PR #17, which was merged about two minutes after it was opened (30 October 2026), and `spec/SWAP-DRILL.md` was later edited directly on `main` (commit `0ff7b56`, an editorial change). `GOVERNANCE.md` requires changes to `spec/` and `schema/` to stay open for at least 14 days. This doesn't make the content wrong, but implementers should know the text has not yet had public review.

None of these change how the reference runtime behaves today. They matter because an independent implementation has no way to know which document formats a given "OPCP version" includes.

## What is guarded now

`tests/test_version_consistency.py` checks the relationships that already hold, so they cannot drift silently:

- the package version, `opcp.__version__`, a `CHANGELOG.md` entry and `docs/releases/v<version>.md` agree;
- every schema's `$id` carries the same version as its `const` version field, where it has one;
- every bundled contract and example route uses the `opcp_version` its schema accepts, and the runtime's `ENVELOPE_VERSION` matches the envelope schema;
- every version marker in the table above is listed in this page, so a new marker cannot appear unrecorded.

The known inconsistencies above are recorded as **expected failures** (`xfail(strict=True)`). When the maintainers resolve one, its test starts passing, pytest reports the unexpected pass, and the marker must be removed in the same change. That keeps this page and the code honest with each other.

## What is not decided

The versioning model is a specification decision. It changes what `opcp_version` means and possibly the schemas, so it goes through the RFC process in `GOVERNANCE.md` (at least 14 days of public review). [ADR 0001](adr/0001-versioning-model.md) sets out the options and a recommendation. Until it is accepted:

- do not change `spec/SPEC.md`'s version header, schema `const` values or `$id`s;
- treat the package version as the only release identifier;
- treat each document's own version field as the authority for that document's format.

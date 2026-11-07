# ADR 0001: Versioning model for the package, the specification and document formats

- **Status:** Proposed. On 2026-11-07 the maintainers chose **option B** to take to public review. The normative text is in the follow-up pull request, which stays open for at least 14 days ([GOVERNANCE.md](../../GOVERNANCE.md) section 3). This record becomes Accepted when that pull request merges.
- **Date:** 2026-11-07
- **Deciders:** the maintainers listed in GOVERNANCE.md

## Context

The repository carries several version numbers that look as if they should agree and do not:

| Where | Value | What it versions today |
|---|---|---|
| `pyproject.toml`, `opcp/__init__.py` `__version__` | `0.3.0` | The Python package (reference runtime and tools) |
| README status line | `draft 0.3` | The release as a whole |
| `spec/SPEC.md` header | `0.2.0` | The core specification document. Unchanged since the 0.2.0 release |
| `spec/SWAP-DRILL.md` title | `OPCP v0.3` | The swap-drill companion, added in the 0.3.0 release |
| `opcp_version` in capability contracts and routes (schema `const`) | `"0.1"` | Undefined in practice. SPEC.md 6.1 says "specification version the contract targets" |
| `opcp_version` in swap-drill evidence (schema `const`) | `"0.3"` | The release in which the swap-drill format first appeared |
| `opcp_version` in `examples/sme-credit-origination.yaml` | `"0.2"` | A provisional, non-normative format with no schema |
| `envelope_version`, `scorecard_version`, `answers_version` (schema `const`) | `"0.1"` | The format of that document type |
| Schema `$id` | `urn:opcp:schema:<v>:<name>` | Matches each schema's own version `const` |
| `opcp.SPEC_VERSION` | `"0.1"` | Not used anywhere in the code |

Read literally, SPEC.md section 6.1 says a capability contract declares the specification version it targets. Under that reading every contract in `catalogue/` targets a specification version (0.1) that is no longer published, while the schema in this repository only accepts `"0.1"`. A contract written today against SPEC.md 0.2.0 cannot say so. The same field name means "first release containing this format" in swap-drill evidence.

The values are internally consistent with one unstated rule: **each document format carries the specification-set version in which its schema last changed.** Capability, route and envelope schemas have not changed since 0.1; the swap-drill schema was introduced in 0.3. The process pack (`"0.2"`) is the one exception, and it is explicitly provisional.

An independent implementer cannot recover that rule from the specification. They need to know which version to emit, which versions to accept, and what a version change means for compatibility.

## Options

### A. Lockstep

One number for the package, the specification and every `opcp_version` field.

- Simple to explain.
- Every package release, including bug fixes to the reference runtime, would change the wire format version and invalidate every stored contract, route and evidence record. This works against the project's goal that the specification is independent of any implementation (GOVERNANCE.md 1.4).

### B. Three independent axes (recommended)

1. **Package version** (`pyproject.toml`). Semantic versioning of the reference implementation only. Released whenever the code changes. Says nothing about protocol compatibility on its own.
2. **Specification version.** One version for the normative set (`spec/` and `schema/`), shown in each specification document's header. Changes only through the RFC process. A minor version adds compatible features; a major version is required for breaking changes (already stated in GOVERNANCE.md 3).
3. **Format version** of each document type (`opcp_version`, `envelope_version`, `scorecard_version`, `answers_version`). Defined as *the specification version in which that document type's schema last changed*. A schema change bumps its format version to the specification version that introduces it; unchanged formats keep their value.

Each release's notes state the package version and the specification version it implements, and list the format versions it reads and writes.

This option keeps every existing document valid: capability contracts and routes stay at `"0.1"`, swap-drill evidence at `"0.3"`. What it changes is the text of SPEC.md section 6.1 (the meaning of `opcp_version`) and the headers of the specification documents, which is why it needs the RFC process.

### C. Leave as is and document

No normative change. Only informative documentation. This leaves SPEC.md 6.1 contradicting the schemas, so implementers still face an ambiguity.

## Decisions the maintainers need to make

1. Choose A, B or C.
2. Under B, the specification-set version for the current text. Candidates: keep SPEC.md at `0.2.0` and SWAP-DRILL.md at `0.3`, or publish both as specification `0.3.0`, the first version that includes the swap-drill companion.
3. Whether the provisional process pack should drop `opcp_version` until it has a schema, so it does not suggest a format version that does not exist.
4. Whether to remove the unused `opcp.SPEC_VERSION` constant or define it as the specification version the package implements.

## What changes now, without a decision

Nothing normative. This ADR records the current state. `tests/test_version_consistency.py` checks the relationships that hold today and that none of the options above would change, so drift is caught in CI while the decision is open:

- the package version is the same in `pyproject.toml` and `opcp/__init__.py`;
- the package version has a CHANGELOG entry and release notes;
- the README status line names the package's major.minor version;
- every schema `$id` carries the same version as the schema's own version `const`;
- the version constants in the reference runtime match the schema `const` they are written against;
- every catalogue contract and example evidence record carries its schema's format version;
- the swap-drill companion's title names the swap-drill format version.

It deliberately does **not** check SPEC.md's header, because what that header should say is the open decision.

## Consequences

Once decided, a follow-up pull request will update SPEC.md 6.1 and the specification headers (open for 14 days), extend the consistency test to cover the specification header, and add the specification version to the release-notes template.

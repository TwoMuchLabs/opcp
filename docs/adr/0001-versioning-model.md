# ADR 0001: Versioning model for the specification, document formats and package

- **Status:** Proposed. Needs maintainer decision through the RFC process (GOVERNANCE.md section 3): normative, at least 14 days of public review.
- **Date proposed:** 2026-11-07
- **Affects:** `spec/SPEC.md` (header, section 6.1, new section), `spec/SWAP-DRILL.md`, every schema's `$id` and version `const`, `opcp/__init__.py`
- **Background:** [docs/VERSIONING.md](../VERSIONING.md) lists every version marker and where they disagree.

## Context

An implementer needs to answer three questions without reading Python code:

1. Which version of the specification does this document or runtime follow?
2. Will a document written for version X validate, and mean the same thing, under version Y?
3. Which package release contains which specification?

Today the repository cannot answer any of them consistently. The package is 0.3.0, the core specification says 0.2.0, the swap-drill companion says v0.3, contracts and routes require `opcp_version: "0.1"`, swap-drill records require `"0.3"`, and section 6.1 tells authors to put "the specification version the contract targets" in a field that only accepts `"0.1"`.

## Options

**A. One version for everything.** Package, specification and every document format share one number, bumped together.
Simple to explain. But every package bug fix bumps the protocol, every document would need re-issuing on each release, and a second implementation can never release on its own schedule. Rejected: it ties the protocol to one implementation, against GOVERNANCE.md section 1.4.

**B. Independent versions with no stated relationship** (today, in effect).
Formats evolve only when they change, which is good. But nothing tells an implementer how they relate, and `opcp_version` means different things in different documents.

**C. A specification version plus per-format versions, separate from the package version.** *(recommended)*

## Recommendation (option C)

1. **The specification has one version**, `MAJOR.MINOR`, shown in the header of `spec/SPEC.md` and of every companion specification (`spec/SWAP-DRILL.md` and future ones). Companion specifications are versioned with the core, not separately. A specification release lists the format versions it includes.
2. **Each document format has its own version**, carried in the document. Keep the existing field names so no document changes shape: `opcp_version` in contracts, routes and swap-drill records is redefined as *the version of that document's format*, and `envelope_version` stays as it is. A format version increases only when that format changes; MAJOR for a breaking change, MINOR for an additive one.
3. **Schema `$id`s carry the format version** (`urn:opcp:schema:<format-version>:<name>`), so a validator can pick the right schema from the document alone.
4. **A compatibility table in the specification** maps each specification version to the format versions it defines, for example:

   | Specification | capability | route | envelope | swap-drill |
   |---|---|---|---|---|
   | 0.3 | 0.1 | 0.1 | 0.1 | 0.1 |

   (Values illustrative. Whether the swap-drill format restarts at `0.1` or keeps `0.3` is part of this decision: renumbering would invalidate the one published example record and any records already produced.)
5. **The package version is independent** and follows semantic versioning for the Python API and CLI. Each package release states which specification version it implements (in release notes and as `opcp.SPEC_VERSION`, which is currently unused and stale).
6. **Runtimes and validators MUST reject a document whose format MAJOR version they do not support**, and SHOULD accept a higher MINOR version only if they ignore unknown optional fields safely. (This needs its own careful wording: today most schemas set `additionalProperties: false`, which makes every additive change breaking for older validators.)
7. **Pre-1.0 rule:** while MAJOR is 0, a MINOR increase may be breaking, and the specification says so.

## Consequences

- Section 6.1's description of `opcp_version` changes meaning. Existing contracts and routes (`"0.1"`) stay valid unchanged.
- The swap-drill record's `opcp_version: "0.3"` either stays as format version 0.3 (no breakage, odd numbering) or becomes 0.1 (breaks existing records). This ADR does not choose; maintainers should.
- A CI check (`tests/test_version_consistency.py`) already enforces the relationships that hold today; once this ADR is accepted, it should also check the compatibility table against the schemas.
- Package releases no longer imply specification changes, and vice versa.

## Questions for reviewers

1. Should companion specifications share the core version (recommended) or be versioned separately?
2. Swap-drill record: keep `"0.3"` or renumber?
3. Should forward compatibility (point 6) be addressed now or in a separate RFC? It interacts with `additionalProperties: false` throughout the schemas.
4. Should the specification adopt `MAJOR.MINOR` only (recommended; patch-level edits are editorial) or full semver?

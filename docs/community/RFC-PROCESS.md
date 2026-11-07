# RFC process

GOVERNANCE.md section 3 says a pull request that changes `spec/` or `schema/` stays open for at least 14 days. This page describes how that works in practice.

## What needs an RFC

| Change | RFC? |
|---|---|
| Any change to the meaning of `spec/` or to a schema in `schema/`, including a new MUST, SHOULD or field, or a tightened type | Yes |
| A new document format or a new companion specification | Yes |
| Wording that leaves the meaning unchanged (typos, links, clearer sentences) | No. Label the PR `editorial`; a maintainer confirms the meaning is unchanged |
| Code, tests, docs outside `spec/`, catalogue contracts, conformance fixtures | No. Lazy consensus |

If in doubt, it needs an RFC.

## Steps

1. **Issue first.** Open an issue with the RFC template (`.github/ISSUE_TEMPLATE/rfc.md`): the problem, evidence (a reproduction where possible), the proposed rule, the compatibility impact, and the conformance tests it needs. The discussion of whether to change anything happens here.
2. **Pull request.** When there is a concrete proposal, open a PR that changes `spec/` or `schema/`. Its first line states that it is normative and when its review period ends (opening date + 14 days). Label it `normative`. Link the issue and, for a significant decision, an ADR in `docs/adr/`.
3. **Review period.** The PR stays open for at least 14 days. A substantive change to it restarts the clock; editorial fixes during review don't. Anyone may comment. Maintainers SHOULD invite at least one implementer or external reviewer to comment ([EXTERNAL-REVIEW.md](EXTERNAL-REVIEW.md)).
4. **Decision.** After the period, a maintainer who is not the author merges, or records why not. Objections are answered in the thread before merging. Disputes go to a majority of maintainers (GOVERNANCE.md section 3).
5. **Record.** The ADR, if any, moves to Accepted or Rejected. The CHANGELOG and release notes list the change and any breaking effects.

## Changes that skipped the process

If a normative change merges without its review period, it isn't reverted automatically. Instead, open a retrospective review: an issue stating what merged early, open for 14 days, after which agreed changes go through a normal RFC. The first one was #34, for the swap-drill specification.

## Urgent changes

A security fix that can't wait 14 days may merge after review by two maintainers. It is announced in the release notes and followed by a retrospective review issue, opened the same day.

## Proposed additions to the repository

Each of these needs the maintainers' agreement:
- labels `normative`, `editorial`, `rfc` and `external-review`;
- a CI check that flags a PR changing `spec/` or `schema/` without the `normative` or `editorial` label, or that is younger than 14 days. It should flag, not block, so maintainers can still see and act on urgent fixes.

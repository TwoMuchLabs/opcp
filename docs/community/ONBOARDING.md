# Contributing, step by step

OPCP is useful only if it reflects how real businesses work. A risk manager who finds an exit question the scorecard misses contributes as much as an engineer who writes an adapter.

## Pick a starting point

| You are | First contribution | Where |
|---|---|---|
| In operations, risk, procurement or legal | Run the scorecard on one of your processes (offline), then open an issue on any question that didn't fit your situation | `opcp scorecard form`, [`questions/`](../../questions/) |
| An architect or engineer | Follow the [quick start](../QUICKSTART.md), then fix a `good first issue` | Issues labelled `good first issue` |
| Building on a supplier's product | Write an adapter for a catalogue contract and run `check_adapter` | [ADAPTERS.md](../ADAPTERS.md) |
| Implementing OPCP in another language | Run the shared conformance fixtures and report any you can't decide from the spec alone | `conformance/`, #40 |
| Reviewing the specification | Join an external review round | [EXTERNAL-REVIEW.md](EXTERNAL-REVIEW.md) |

## What a good first pull request looks like

- **Small:** one change, with its tests.
- **Signed off** under the Developer Certificate of Origin (`git commit -s`, see [CONTRIBUTING.md](../../CONTRIBUTING.md)).
- **Sourced:** any regulatory mapping, standard identifier or vendor capability cites where it comes from.
- **Explicit about the specification:** if it touches `spec/` or `schema/`, it follows the [RFC process](RFC-PROCESS.md).

## What you can expect from maintainers

These are proposed service levels, and maintainers report against them quarterly:
- a first response on a new issue or PR within 5 working days;
- a decision, or a clear list of what's needed, within 15 working days of a PR being ready;
- a reason whenever something is declined.

## AI-assisted contributions

Contributions written with AI assistance are welcome, on three conditions:

1. **A person signs off every commit.** The DCO is a statement by a person about their right to contribute. An AI agent can't make it. A maintainer adopting AI-authored work adds their own sign-off when merging.
2. **Disclosure.** The PR says AI assistance was used. Commit trailers (`Co-Authored-By`) are enough.
3. **The same bar as any other contribution:** tests, sources, and the RFC process for specification changes.

In November 2026 much of the review and fix work in this repository was produced by AI agents working for a maintainer, with that maintainer deciding what merges. This section records that practice so others can see it and follow it.

# External technical review

OPCP asks regulated firms to trust it with how their processes are governed. That trust has to come from people outside the project, so the specification is reviewed in rounds by practitioners who don't maintain it.

## Who reviews

Each round aims for at least three reviewers, from at least two organisations that don't employ a maintainer, covering:
- **an operator:** someone who runs or controls a critical process in a regulated firm (operations, operational risk, third-party risk);
- **an architect or engineer** who would have to build or integrate it;
- **an implementer:** someone who would write a second implementation, or has tried to.

Reviewers take part as individuals. They don't speak for their employers, and they never share anything confidential to them.

## What a round covers

One focused area per round, so that it can be reviewed in about four hours:

| Round | Area | Material |
|---|---|---|
| 1 | Supplier swap drills and their evidence | `spec/SWAP-DRILL.md`, #34, #30 |
| 2 | Authority: gate, Reversibility Classes, delegation | SPEC section 10, #37, #27 |
| 3 | Context and data: lease, classification, residency | SPEC sections 9.1 and 11, #36 |
| 4 | Interoperability: versioning, conformance, a second implementation | SPEC sections 2.1 and 13, #40, #44 |

## How it runs

1. A maintainer opens a tracking issue for the round, with the material, the questions and a four-week window.
2. Reviewers file findings with the external-review issue template, or in a private message to hello@twomuchlabs.com when a finding is security-relevant (SECURITY.md).
3. Within two weeks of the window closing, maintainers answer every finding: accepted (and an RFC opened), declined with a reason, or deferred with a milestone.
4. The round closes with a short public summary listing what was found and what changed. Reviewers are credited by name unless they ask not to be.

## Independence

- Reviewers disclose any commercial interest in OPCP, in a product built on it, or in a competing approach.
- No non-disclosure agreements, and no payment tied to a favourable outcome.
- A reviewer may publish their own view of the specification at any time.

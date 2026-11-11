# Open Process Control Plane (OPCP)

**Own your processes, your context and your authority. Rent capabilities from any supplier.**

Superapps and vendor AI agents are absorbing how businesses run: their rules, their accumulated know-how and the authority to act. Replacing a supplier then means rebuilding part of the business. Regulators in the EU, Australia and Singapore increasingly expect regulated firms to manage this concentration and to hold workable exit plans (see [spec section 15](spec/SPEC.md#15-relationship-to-other-work-informative)).

OPCP is an open framework for the opposite arrangement. The business keeps its process logic, its context and its authority in open formats it controls. Vendors, internal systems and human teams plug in underneath through standard capability contracts, so any of them can be swapped.

> **Status:** draft 0.3 for comment. The specification, schemas and tools will change based on feedback.

## What is in this repository

| | What it is | Start here |
|---|---|---|
| **Specification** | Capability archetypes, the standard envelope, capability contracts, two-stage routing, the authority gate, context lease, the Exit-Readiness Scorecard and conformance | [`spec/SPEC.md`](spec/SPEC.md) |
| **Schemas** | JSON Schemas for contracts, routes, envelopes and scorecard assessments | [`schema/`](schema/) |
| **Catalogue** | Example capability contracts for five archetypes | [`catalogue/`](catalogue/) |
| **Exit-Readiness Scorecard** | A local tool that rates how dependent each critical process is on its supplier, and writes a one-page report | `opcp scorecard` |
| **Swap drill** | A portable, pass-or-fail test that a capability can move from one supplier to another without changing the process, context lease or authority policy | [`spec/SWAP-DRILL.md`](spec/SWAP-DRILL.md) · `opcp swap-drill` |
| **Reference runtime** | A minimal control plane: router, authority gate, context lease, event log and conformance runner | [`opcp/`](opcp/) · `opcp demo` |

## Try the scorecard in two minutes

**Before you start.** You need Python 3.10 or later. Check with `python3 --version` (or `python --version` on Windows). Install the package from PyPI:

```bash
pip install opcp
```

To use the latest unreleased version instead, run `pip install .` inside a copy of this repository.

Then:

```bash
opcp scorecard example                  # copies a filled-in, hypothetical example
opcp scorecard run example-assessment.yaml -o report.html
```

If your system says `opcp` is not found, use `python -m opcp` instead, for example `python -m opcp scorecard example`.

### Assess your own processes

1. **Create the form.** `opcp scorecard form` writes `assessment-form.html`. Open it in any browser; it works offline and nothing leaves your device.
2. **Answer the questions.** Each question says who is best placed to answer it (process owner, procurement or legal, technology, risk) and what evidence would support the answer. Start with three triage questions; only critical processes need the full set.
3. **Download the answers file** from the form, and send the form to colleagues if others need to contribute.
4. **Rate it.** `opcp scorecard run answers.json -o report.html`

Prefer a text editor? `opcp scorecard init my-assessment.yaml` writes a commented YAML template to fill in by hand; see [`examples/example-bank-answers.yaml`](examples/example-bank-answers.yaml) for a completed one. Add `--json results.json` to `opcp scorecard run` for machine-readable results.

Running it as a pilot across several processes? [docs/PILOT.md](docs/PILOT.md) sets out a six-week plan, who answers what, and a readout agenda. [docs/SWAP-DRILL.md](docs/SWAP-DRILL.md) explains how to rehearse a supplier swap, so a time-to-swap figure becomes proven rather than estimated.

### What the report rests on, and its limits

- **A standard question bank.** Every firm answers the same [22 questions](questions/exit-readiness.yaml) with the same anchored options, so results are comparable.
- **Evidence levels.** Each answer is Declared, Documented (a named record) or Tested (demonstrated in the last 12 months). Each measure shows its weakest evidence.
- **Clause-level references.** Questions cite the obligations they relate to across DORA and its technical standards, the EU Data Act, EBA, APRA CPS 230, MAS, the PRA, the FSB, the Basel Committee, IOSCO, NIST and CSA: 74 references to 15 sources. Each source records how its text was checked, and a second reviewer spot-checked about 45 locators. See [docs/REFERENCES.md](docs/REFERENCES.md).
- **Published research.** [docs/EVIDENCE.md](docs/EVIDENCE.md) sets out why each measure matters, from 20 verified sources: peer-reviewed papers, supervisory and central-bank analysis, a competition-authority decision, government and intergovernmental reports, an industry outage study and one preprint (labelled as such).
- **Honest status.** Every report says it is a self-assessment against a published method, not a certification, and shows who prepared it and whether it was independently reviewed.

Preparing for a decision meeting? `opcp scorecard readout answers.json -o readout.html` writes a two-page sponsor pack: where each process stands, the decisions to take, and each contract's last day to give notice.

Using process-mining tools? `opcp ocel events.jsonl -o events.ocel.json` converts the runtime's event log to OCEL 2.0. See [docs/PROCESS-MINING.md](docs/PROCESS-MINING.md).

Already filing an EU DORA register of information? `opcp scorecard export answers.json -o dora.csv` suggests register values from your answers, with the reasoning for each. See [docs/REGISTERS.md](docs/REGISTERS.md).

**Your data stays on your machine.** The scorecard makes no network calls and sends no telemetry. The report is a single self-contained HTML file.

### What the scorecard measures

For each process: where the rules live, whether learned context can leave, whose permission model governs actions, supplier-only dependencies, contract exit terms, time-to-swap (contracting, onboarding and cutover, estimated or proven), and whether a fallback supplier exists. Each process is rated by its **weakest** measure, because an exit fails at its weakest point. Across critical processes, it shows the share each supplier serves and flags any above your concentration limit.

## See the reference runtime

```bash
opcp demo               # six calls through the control plane, with simulated suppliers
opcp conformance-demo   # adapter conformance checks against the example contracts
opcp swap-demo          # a shadow swap drill between two simulated document-extraction suppliers
opcp swap-drill examples/sme-credit-swap-drill.json   # evaluate a swap-drill evidence record
```

The demo shows the main ideas working together:

- a cascade that excludes suppliers failing hard rules (unapproved, wrong data region) before scoring anyone;
- escalation to a human review team when no supplier is confident enough;
- a context lease that withholds any field the contract does not declare;
- an authority gate using Reversibility Classes R0–R4: a ledger posting within a pre-approved budget, a second one stopped, a customer email never sent autonomously, and an unknown capability failing closed.

## Key ideas

- **Seven archetypes.** Every capability is one of `check`, `extract`, `generate`, `transact`, `retrieve`, `notify` or `human_task`. Domains are numerous; interaction shapes are few, so integrations become configuration.
- **One envelope.** Every call carries the same fields: trace and idempotency keys, leased input, evidence, confidence, cost, Reversibility Class and the reason for the route.
- **Two-stage routing.** Hard eligibility rules first, never traded off. Scores choose among the survivors.
- **Swaps are proven, not promised.** A swap drill passes only if six gates all hold: process, context lease and authority policy unchanged, contract conformance, business regression cases, and no material exception downgraded. Gates are never averaged. See [`spec/SWAP-DRILL.md`](spec/SWAP-DRILL.md).
- **Reversibility, not severity.** The authority gate uses the R0–R4 classes from [Reversibility Classes for Agent Actions](https://github.com/TwoMuchLabs/reversibility-classes).

## Open by design

OPCP must not become the next concentration risk, so its openness is built to be hard to reverse:

- **Apache 2.0 for all of the project's own material**, including the specification. The R0–R4 classes it references come from the Reversibility Classes specification, also Apache 2.0; see [NOTICE](NOTICE).
- **No contributor licence agreement.** Contributors keep their copyright, so no single party can relicense the project.
- **Specification independent of implementation**, with public conformance tests.
- **A stated path to a neutral foundation.**

See [GOVERNANCE.md](GOVERNANCE.md).

## Authors

Deepak Waghmare and Shaad Sufi, with contributors.

## Contributing

Operations, risk, legal and procurement expertise is as welcome as code. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Contact

Questions about the project: hello@twomuchlabs.com. To report a security issue, see [SECURITY.md](SECURITY.md).

## Licence

[Apache License 2.0](LICENSE). Nothing in this repository is legal or regulatory advice.

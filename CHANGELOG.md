# Changelog

## Unreleased

- **Versioning documented.** `docs/VERSIONING.md` lists every version marker (package, specification, document formats, schemas, question bank) and where they disagree; `docs/adr/0001-versioning-model.md` proposes a model for public review. `tests/test_version_consistency.py` guards the relationships that already hold and records the known inconsistencies as expected failures. No version numbers were changed.
- README: install from PyPI (`pip install opcp`); the status line now gives the package and specification versions separately.
- NOTICE and README now record that the Reversibility Classes specification is licensed under Apache 2.0 (from its v0.3.1); it was CC BY 4.0 before.

## 0.3.0 (draft) — 2026-11-02

Supplier portability becomes something you can test, not just assess.

- **Swap-drill specification** (`spec/SWAP-DRILL.md`, `schema/swap-drill.schema.json`). A normative companion to the specification. A drill runs a candidate supplier in shadow beside the incumbent on the same contract and business-owned regression cases. It passes only if all six gates hold: process, context lease and authority policy unchanged, contract conformance, regression cases passed, and no material exception (an expected fail or refer) turned into a pass. Gates are never averaged or traded off. Time-to-swap is reported in three parts, and a `proven` figure must carry a drill date. The spec lists the conformance fixtures every implementation must include.
- **Swap-drill tools.** `opcp swap-drill <evidence.json>` evaluates a drill evidence record and reports the decision, whether the candidate is ready to promote, any errors and the regression counts. `opcp swap-demo` runs a shadow drill between two simulated suppliers and prints the resulting record. The evaluator is deterministic and has no dependency on any commercial product.
- **Example process pack** (`examples/sme-credit-origination.yaml`, provisional) and a matching drill record (`examples/sme-credit-swap-drill.json`). The process-pack format is not yet normative.
- **Sponsor readout** (`opcp scorecard readout`). A two-page, printable pack for the pilot's decision meeting. It shows a grid of every critical process against the seven measures, summary tiles (ratings, evidence coverage, proven swaps, largest supplier share), the decisions for the sponsor in order of urgency, and each renewing contract's last day to give notice (end date minus notice period). Release builds attach an example readout.
- **OCEL 2.0 export** (`opcp ocel`, `docs/PROCESS-MINING.md`). Converts an exported event log to OCEL 2.0 JSON for process-mining tools. Requests, capabilities, processes and suppliers become objects, and each log entry becomes an event linked to them. No input or output values are exported unless the log holds them. Checked by reading the demo log with PM4Py's OCEL 2.0 reader.
- **Fix:** the control plane now uses the event log it is given, even when that log is empty.

## 0.2.0 (draft) — 2026-10-24

A standard way to collect inputs, and the evidence behind the method.

- **Question bank** (`questions/exit-readiness.yaml`, version 0.2): 22 questions with stable IDs, anchored options, a named respondent role for each, evidence guidance, triage and five consistency checks.
- **Evidence levels**: every answer is Declared, Documented or Tested; reports show each measure's weakest evidence and the share of answers backed by a record or test.
- **Framework references**: 74 clause-level references to 15 regulations, guidelines and standards (DORA and its RTS, EU Data Act, EBA, APRA CPS 230, MAS, PRA, FSB, Basel Committee, IOSCO, NIST, CSA). Each source records how its text was checked; about 45 locators were spot-checked by a second reviewer. Optional filter by jurisdiction.
- **Research base** (`docs/EVIDENCE.md`, `docs/REFERENCES.md`): 20 verified sources, from peer-reviewed papers to supervisory analysis, explaining why each measure matters.
- **Offline form** (`opcp scorecard form`): one HTML file, no network, saves progress in the browser, exports an answers file.
- **Reports** now state they are a self-assessment, show sign-off and review, consistency flags, evidence and references.
- New question: whether the firm can terminate on a regulator's direction.
- **Register export** (`opcp scorecard export`, `docs/REGISTERS.md`). Suggests EU DORA register of information values (B_07.01 substitutability, reason, exit plan, reintegration and alternative providers, plus the B_02.02 end date and notice period) for each critical process, with the reasoning for each value. It is a suggestion for review, not a filing, and never suggests "Not substitutable". The UK, APRA and MAS registers are not yet supported.
- **Pilot playbook** (`docs/PILOT.md`) and **swap-drill guide** (`docs/SWAP-DRILL.md`): a six-week pilot plan, who answers which questions, a readout agenda, and how to rehearse a supplier swap so a time-to-swap becomes proven.
- **Release automation**: CI on Python 3.10 to 3.13, and a release workflow with PyPI trusted publishing (`docs/RELEASING.md`).

## 0.1.0 (draft) — 2026-10-24

First public draft for comment.

- Specification v0.1: capability archetypes, standard envelope, capability contracts, two-stage routing, authority gate, context lease, exit-readiness scorecard, conformance.
- JSON Schemas for capability contracts, routes, envelopes and scorecard assessments.
- Example catalogue: five capability contracts covering the Check, Extract, Notify, Transact and Human task archetypes.
- Exit-Readiness Scorecard: local command-line tool that turns an assessment file into a one-page HTML report.
- Reference runtime: minimal control plane with router, authority gate, context lease, event log and conformance runner, plus a runnable demo.

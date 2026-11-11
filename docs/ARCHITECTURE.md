# Architecture

OPCP splits a business process into what the business **owns** and what it **rents**. The owned layers are open documents and an open log. The rented layer is any supplier that fulfils a published contract. This page explains how the parts fit; [`spec/SPEC.md`](../spec/SPEC.md) is the authority on every rule mentioned.

## The parts

| Part | Owned or rented | What it is | Spec |
|---|---|---|---|
| Capability contract | Owned | What a capability does, independent of who does it: one of seven archetypes, input and output schemas, a Reversibility Class (R0–R4) and the highest data classification it may receive | 5, 6 |
| Route | Owned | Which suppliers may fulfil a capability, in what order or mode, approved by a second person | 9 |
| Authority policy | Owned | What each Reversibility Class may do without approval, plus budgets, approvers and overrides | 10 |
| Event log | Owned | Every request, gate decision, route decision and response, in JSON Lines | 11.1 |
| Supplier profile | Owned | What the business has approved about a supplier: register reference, contract end, regions, classifications, highest class it may perform, conformance status | 8.2 |
| Adapter | Shared | Software connecting one supplier to one contract | 8 |
| Supplier | Rented | A vendor, an internal system or a human team | 3 |

## What happens on every call

```
caller ──request envelope──▶ control plane
                             1. contract found?            no ─▶ rejected, as R4 (fail closed)
                             2. context lease               strip every field the contract doesn't declare
                             3. request valid?              schema, classification, accountable role
                             4. authority gate              by Reversibility Class: allow, notify, budget or approval
                             5. eligibility (9.1)           approved, in contract, conformant, classification,
                                                            residency, authorised class, healthy
                             6. selection (9.2, 9.3)        pinned, segmented, cascade, weighted or best_score
                             7. adapter ──▶ supplier        leased input only
                             8. output checked              contract schema, archetype fields, evidence
                             9. event log                   every step above is recorded
caller ◀─response envelope── status, output, evidence, class, supplier, reason for the route
```

The order matters. The gate runs **before** any supplier is contacted. Eligibility filters are **never** traded off against scores. The lease is applied **before** anything leaves the control plane.

## What OPCP is not

- **Not a workflow engine.** It governs one capability call at a time. Sequencing steps into a process is the job of whatever runs the process (a BPM engine, application code, an agent). The process pack format in `examples/` is provisional and not part of the specification.
- **Not a transport.** Contracts say *what* a capability does. An adapter may call a REST API, a queue, an MCP server or a person's work queue.
- **Not identity or access management.** The `principal` on a request is taken as given. Authenticating it, and per-principal delegation (#37), are outside the current specification.
- **Not a policy language.** The authority gate applies a fixed decision per Reversibility Class plus budgets, approvers and overrides. It does not evaluate arbitrary rules, and it never consults a model.
- **Not a certification.** The Exit-Readiness Scorecard is a self-assessment against a published method, and its references show relevance, not compliance.

## Relationship to adjacent work

| Work | Relationship today |
|---|---|
| [Reversibility Classes for Agent Actions](https://github.com/TwoMuchLabs/reversibility-classes) | Supplies the R0–R4 vocabulary the gate uses (spec 10) |
| Model Context Protocol (MCP) | A possible transport for adapters that wrap AI tools (spec 15). No MCP integration ships today. |
| OCEL 2.0 | The event log converts to OCEL 2.0 for process-mining tools (`opcp ocel`, [PROCESS-MINING.md](PROCESS-MINING.md)) |
| APQC PCF, BIAN | Suitable taxonomies for mapping contracts and processes (spec 15). Catalogue mappings are proposed in #2. |
| OpenTelemetry, Open Policy Agent | No integration. Both are being assessed for genuine interoperability gaps before anything is proposed. |
| EU DORA, APRA CPS 230, MAS guidelines | The scorecard is designed to support exit planning under these. It is not legal or regulatory advice (spec 15). |

## The reference implementation

`opcp/` is one implementation of the specification, in Python. The modules map to the parts above:

| Module | Part |
|---|---|
| `contract.py` | Contracts and the context lease |
| `adapter.py` | Adapters and supplier profiles |
| `router.py` | Routes, eligibility, selection and concentration limits |
| `gate.py`, `rclass.py` | Authority gate and Reversibility Classes |
| `runtime.py` | The control plane: the call sequence above |
| `eventlog.py`, `ocel.py` | Event log and OCEL export |
| `swap.py`, `swap_drill.py` | Supplier swap drills ([`spec/SWAP-DRILL.md`](../spec/SWAP-DRILL.md)) |
| `scorecard.py`, `questionbank.py`, `readout.py`, `registers.py` | Exit-Readiness Scorecard tools |

Another implementation should need only `spec/`, `schema/`, `catalogue/` and the shared conformance fixtures. Where it doesn't, that is a gap in the specification and worth an issue (see #40).

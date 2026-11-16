# Conformance fixtures

Machine-readable test cases that any OPCP implementation can run, in any language. They are test data, not specification: the rules they check are in [`spec/`](../spec/), and each fixture names the section it exercises.

## Format

Each fixture is one JSON file:

```json
{
  "id": "SD-10-revisions-differ-gate-true",
  "guarantee": "What protocol rule this case checks, with the spec section.",
  "expected_outcome": "pass | fail | reject",
  "evidence": { "...": "the input document" }
}
```

Outcomes are defined so that implementations do not have to match each other's error messages:

| Outcome | Meaning |
|---|---|
| `pass` | The input is valid and the candidate is promotable. |
| `fail` | The input is valid, and at least one promotion gate correctly blocks promotion. |
| `reject` | The input is not a valid record: it breaks the schema or an invariant, or contradicts itself. |

## Suites

| Directory | Specification | Fixtures |
|---|---|---|
| [`swap-drill/`](swap-drill/) | [`spec/SWAP-DRILL.md`](../spec/SWAP-DRILL.md) | SD-01 to SD-15, covering every case listed in section 8 plus invariant, count and decision consistency |
| [`runtime/`](runtime/) | [`spec/SPEC.md`](../spec/SPEC.md) sections 5 to 11 and 13 | RT-01 to RT-39: authority gate, eligibility filters, context lease, routing modes, escalation, concentration limits, output validation, maker-checker and idempotency |

## Runtime fixtures

The swap-drill format above describes one document. A runtime fixture describes a small world and a sequence of calls through it:

```json
{
  "id": "RT-15-lease-strips-undeclared-fields-at-every-depth",
  "guarantee": "What protocol rule this case checks, with the spec section.",
  "setup": {
    "today": "2026-11-07",
    "contracts": ["verify-identity"],
    "suppliers": [{"adapter_id": "a", "supplier_id": "A", "capability": "verify-identity",
                   "behaviour": {"respond": {"output": {"verdict": "pass", "reason_codes": []},
                                             "evidence": [{"type": "report", "reference": "r1"}],
                                             "confidence": 0.95}}}],
    "routes": [{"opcp_version": "0.1", "capability": "verify-identity", "...": "a route document"}],
    "gate": {"budgets": {}, "overrides": {}, "two_person_r4": false, "approvals": []}
  },
  "calls": [{"capability": "verify-identity", "input": {}, "data_classification": "confidential",
             "idempotency_key": "k1", "expect": {"status": "ok", "supplier": "A"}}],
  "expect_final": {"invocations": {"a": 1}, "received": {"a": [{"...": "exact input the supplier got"}]}}
}
```

**Setup.**

- `contracts` lists catalogue ids from [`catalogue/`](../catalogue/), or whole contract documents for cases the catalogue doesn't cover.
- `routes` are route documents (`schema/route.schema.json`).
- `suppliers` are supplier profiles (spec 8.2) plus a scripted `behaviour`: `respond` returns the given output, or `error: true` fails *definitely*, with no effect. Unknown outcomes are not scripted until #27 settles their semantics. Supplier fields a fixture leaves out take these defaults: `kind` vendor, `register_ref` "TPR-1", `approved` true, `conformance_passed` true, `contract_major` 1, `contract_end` "2030-01-01", `max_data_classification` "confidential", `regions` ["SG"], `max_rclass` "R0".
- `gate.approvals` are the approver's answers, consumed in order. If the key is absent, no approver is configured.
- `concentration_limit` (optional) is the largest share of critical routes any one supplier may serve as primary (spec 9.4).
- `human` suppliers (`"kind": "human"`) report no confidence; they are how cascades and escalation end.

**Calls.** Each call gives the envelope fields of spec 7.1. Defaults for omitted fields: `process_id` "p", `step` "s", `principal` "agent", `accountable_role` "Process owner".

**What may be asserted.** Only facts an outside observer can check, so implementations need not share internals or log formats:

| Field | Meaning |
|---|---|
| `status`, `supplier`, `rclass` | The response envelope (spec 7.2). `supplier` is the supplier id, or `null` if none served the call. |
| `gate_decision` | Whether a gate decision was recorded for this call (spec 10.6), as `{allowed, rclass}`, or `null`. |
| `expect_final.invocations` | How many times each supplier actually performed the capability. |
| `expect_final.received` | Exactly what each supplier received, in call order: the context lease (spec 11.2). |
| `expect_setup_rejected` | The configuration itself must be refused, for example a route without maker-checker (spec 9). |

An expectation a fixture leaves out is not checked.

## Running them

The reference implementation runs the swap-drill fixtures in `tests/test_conformance_fixtures.py` and the runtime fixtures in `tests/test_runtime_conformance.py`, which is its *harness*: it builds the world, makes the calls and reports the observable facts above. Another implementation should load each swap-drill file, evaluate `evidence`, map its result to one of the three outcomes, and compare with `expected_outcome`; for runtime fixtures, it writes its own harness over the same files.

Each runtime fixture was checked against a deliberately broken runtime: disabling the rule it names (one of 25 rules: the lease, each eligibility filter, the gate, budgets, two-person approval, `best_score`, failover, cascade, maker-checker and four idempotency rules) makes that fixture fail.

## Adding a fixture

One fixture checks one rule. Change a single thing from a passing record, keep everything else consistent (counts, gates, decision), and state the rule in `guarantee`. A fixture that fails for several reasons cannot show which rule an implementation enforces.

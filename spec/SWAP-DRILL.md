# Supplier Swap Drill

**Version:** 0.3.0 (draft), a normative companion to [`SPEC.md`](SPEC.md), versioned with it (SPEC.md section 2.1)
**Format version of swap-drill records:** `opcp_version: "0.3"`

A supplier swap drill proves that a capability can move from an incumbent supplier to a candidate supplier without moving ownership of the business process, context or authority boundary.

## 1. Scope

A swap drill evaluates one capability contract, one incumbent supplier and one candidate supplier against the same business-owned process and regression cases. It is an OPCP interoperability primitive that any conformant control plane can run.

A conforming implementation **MUST** produce a machine-readable result that validates against [`../schema/swap-drill.schema.json`](../schema/swap-drill.schema.json).

## 2. Shadow execution

A drill **SHOULD** run in `shadow` mode before promotion:

- the incumbent remains the live supplier;
- the candidate receives the same eligible test inputs;
- candidate outputs are evaluated against the same business-owned expectations;
- candidate execution **MUST NOT** create customer-visible effects or apply authority effects;
- the process, context lease and authority policy used for the candidate **MUST** be the same revisions used by the incumbent.

A `rehearsal` MAY execute a controlled cutover in a non-customer-facing environment. `production` is reserved for a completed promotion and is not a prerequisite for proving a drill.

## 3. Invariants

The result **MUST** identify the incumbent and candidate revisions for all three ownership boundaries:

1. **Process.** The process definition and step contract remain unchanged.
2. **Context lease.** The fields and lease semantics exposed to the candidate remain unchanged.
3. **Authority policy.** The authority and Reversibility Class policy remain unchanged.

An implementation **MUST NOT** mark the corresponding promotion gate true unless the two revisions are equal in the comparison performed for the drill.

## 4. Promotion gates

A candidate is promotable only when **all six** gates are true:

1. `process_unchanged`
2. `context_lease_unchanged`
3. `authority_policy_unchanged`
4. `contract_conformance`
5. `regression_pass`
6. `material_exception_regression`

The decision **MUST** be `passed` if and only if every gate is true. A failed gate **MUST** block promotion; implementations **MUST NOT** average, weight or otherwise trade off these gates.

## 5. Regression semantics

Regression cases are business-owned test cases. Each case records the expected outcome, incumbent outcome and candidate outcome.

A case **MUST** pass when the candidate preserves the expected business outcome. A material exception is an expected `fail` or `refer` outcome. Changing such an outcome to a non-exception outcome is a material exception regression and **MUST** fail the material-exception gate.

The result **MUST** report total, passed and failed case counts and include the individual case records. Confidence values are optional supplier claims and **MUST NOT** substitute for business regression results.

## 6. Time-to-swap

A drill result **MUST** report time-to-swap in three components:

- `contracting_days`
- `onboarding_days`
- `technical_cutover_days`

The result **MUST** distinguish `estimated` from `proven`. An estimated figure describes a plan or projection. A proven figure is backed by a completed drill and **MUST** include `drill_date`.

Implementations **MUST NOT** label a simulated demo as proven merely because elapsed wall-clock time was supplied to the evaluator.

## 7. Evidence and portability

The swap result is itself portable evidence. Implementations **SHOULD** retain references to the contract conformance result, regression suite and relevant process/context/authority revisions without embedding supplier-proprietary artefacts in the protocol record.

The standard result is intentionally independent of a supplier SDK, commercial dashboard or procurement system. Those systems MAY consume the result and add proprietary analytics, but another OPCP implementation **MUST** be able to validate and interpret the core decision without them.

## 8. Conformance fixtures

A conformance suite for this version **MUST** include at least:

- a passing swap with unchanged process, context lease and authority policy;
- a process-change failure;
- a context-lease change failure;
- an authority-policy change failure;
- a contract-conformance failure;
- a regression failure;
- a material-exception regression failure;
- an estimated time-to-swap result; and
- a proven result without `drill_date`, which **MUST** be rejected by schema validation.

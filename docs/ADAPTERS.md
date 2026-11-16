# Writing an adapter

An adapter connects one supplier to one capability contract (spec section 8). The control plane decides **whether** and **to whom** a call goes. The adapter only does the call. Start from the working example in [`examples/quickstart/quickstart.py`](../examples/quickstart/quickstart.py).

## 1. Implement `invoke`

```python
from opcp.adapter import Adapter, AdapterResult

class AcmeScreening(Adapter):
    def invoke(self, payload, request):
        reply = acme_client.screen(name=payload["full_name"])          # the supplier's own API
        return AdapterResult(
            output={"verdict": reply.verdict, "reason_codes": reply.codes},
            evidence=[{"type": "acme_report", "reference": reply.report_id}],
            confidence=reply.score,        # optional; a supplier's claim, not a measurement
            cost=0.40,                     # optional; currency comes from the supplier profile
        )
```

- `payload` is already **leased**: it holds only the fields the contract declares (spec 11.2). Don't look for other fields; they were removed on purpose.
- `request` is the envelope (`trace_id`, `idempotency_key`, `principal`, `process_id`, `step`, `residency` and so on). Pass `request.idempotency_key` to the supplier if its API supports idempotency keys.
- Map the supplier's identifiers into the contract's output. Never put the supplier's proprietary fields into a contract's required fields (spec 6.3).

## 2. Return what the contract and archetype require

The control plane checks every output before accepting it:

| Check | Source |
|---|---|
| Output validates against the contract's output schema | Contract `output` |
| Output has the archetype's required fields, for example `verdict` and `reason_codes` for `check` | Spec 5 |
| Evidence is present when required (by default for `check` and `transact`) | Contract `evidence_required` |

Output that fails any check is discarded, and the call moves to the next candidate or fails. A `transact` must say in `compensation` how its effect can be undone, or `none` (spec 5, rule 3).

## 3. Describe the supplier in its profile

```python
from opcp.adapter import SupplierProfile
from opcp.rclass import RClass
import datetime as dt

profile = SupplierProfile(
    adapter_id="acme-screening",          # what routes refer to
    supplier_id="Acme Screening Ltd",     # who the supplier is
    kind="vendor",                        # vendor, internal or human
    register_ref="TPR-0412",              # required for vendors: the third-party register entry
    capability="screen-name",
    contract_major=1,                     # the contract major version this adapter implements
    approved=True,                        # approved in the third-party register
    contract_end=dt.date(2027, 6, 30),
    conformance_passed=True,              # set only after check_adapter passes
    max_data_classification="confidential",
    regions=frozenset({"SG"}),            # where the supplier processes data
    max_rclass=RClass.R0,                 # the highest class it is authorised to perform
)
```

Each of these fields feeds an eligibility filter (spec 9.1). A wrong value doesn't break the adapter; it makes the supplier ineligible, or eligible when it shouldn't be. Treat profiles as security-relevant configuration (spec 14).

## 4. Errors and retries

- **Raise an exception when the call fails.** The control plane records it and tries the next eligible candidate.
- **Be careful with effects.** If the supplier may have acted before the error, for example a timeout after a payment request was sent, the outcome is *unknown*. The current specification doesn't distinguish unknown from failed, and the reference runtime fails over, which can repeat the effect at another supplier. Until #27 is settled, put `transact` and `notify` capabilities on routes with a single candidate, or make sure the supplier's own idempotency covers retries.
- **Idempotency.** The `Adapter` base class remembers results per principal, idempotency key and payload, so a repeated call doesn't reach the supplier twice within one process. That memory is not durable across restarts (#31).

## 5. Don't keep leased data

An adapter MUST NOT retain leased input after the call (or after `lease_expires_at`), unless the supplier contract permits it and that permission is recorded in the profile (spec 8.4). This includes logs and caches on the adapter side.

## 6. Check conformance

```python
from opcp.conformance import check_adapter
report = check_adapter(adapter, contract)
print(report.render())
```

This runs every `examples` entry in the contract through the adapter and checks the output, the evidence, the confidence range, and that a repeated key does not repeat the effect. It calls the real supplier, so use a test environment. Set `conformance_passed=True` in the profile only after it passes.

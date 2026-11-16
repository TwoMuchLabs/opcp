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

- **Say whether the supplier acted.** Raise `opcp.adapter.DefiniteFailure` when the supplier certainly did nothing: it refused the request, or the connection failed before the request was sent. Raise anything else, or let a timeout propagate, when the supplier *may* have acted. The outcome is then *unknown*.
- **What the control plane does with each.** After a definite failure it tries the next eligible candidate. After an unknown outcome it depends on the capability:
  - For R0 and R1 checks, extractions and other calls without a lasting effect, it also fails over.
  - For R2 and above, and for every `transact` or `notify` capability, it stops. Trying another supplier could post, pay or send twice under the same idempotency key (spec 7.1, issue #27). The response is `failed`, with `outcome: "unknown"` and `supplier` naming the supplier to reconcile with. The pre-approved budget unit is not refunded.
  - A retry with the same idempotency key goes back to that supplier only, even if the route has changed. Your adapter must pass the key on so the supplier deduplicates (section 4, below). If the supplier then reports a definite failure, the key is released and the next candidates are tried.
- **Invalid output counts as unknown for effectful capabilities.** A payment adapter that returns a receipt the contract rejects has probably paid. Fix the mapping; the runtime won't hide it by trying another supplier.
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

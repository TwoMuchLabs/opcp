# Quick start (15 minutes)

By the end you will have run a capability call through an OPCP control plane, seen the context lease and the authority gate work, written an adapter, and checked it for conformance. Nothing leaves your machine.

You need Python 3.10 or later.

## 1. Install (1 minute)

```bash
pip install opcp
opcp --version
```

If your shell says `opcp` is not found, use `python -m opcp` instead.

## 2. Run the example (3 minutes)

Get the example from this repository (`examples/quickstart/`) and run it:

```bash
python examples/quickstart/quickstart.py
```

You should see:

```
1. ok: verdict pass from Compliance systems
   lent ['country', 'full_name'], withheld ['salary']
2. retry with the same key: ok, same trace: True
3. residency MY: failed (no eligible supplier: watchlist-inhouse: processes data outside permitted regions (SG))
4. unknown capability: rejected as R4
Event log: 13 entries, every gate decision included.
```

What happened:

1. **Context lease** (spec 11.2). The caller passed `salary`, but the contract declares only `full_name` and `country`, so the supplier never received it, and the event log records what was lent and what was withheld.
2. **Idempotency** (spec 7.1). The retry with the same key returned the first response instead of calling the supplier again.
3. **Eligibility** (spec 9.1). The request allowed only Malaysia. The only supplier processes in Singapore, so it was excluded before anything was sent.
4. **Fail closed** (spec 10.2). A capability with no contract is treated as R4, the highest Reversibility Class, and refused.

## 3. Read the three files (5 minutes)

| File | What it is | Spec |
|---|---|---|
| [`screen-name.yaml`](../examples/quickstart/screen-name.yaml) | The **capability contract**: archetype, input and output schemas, Reversibility Class, data classification. The business owns it. | 5, 6 |
| [`screen-name.route.yaml`](../examples/quickstart/screen-name.route.yaml) | The **route**: which supplier fulfils the capability and how, approved by a second person. | 9 |
| [`quickstart.py`](../examples/quickstart/quickstart.py) | An **adapter** (20 lines), its **supplier profile**, and the calls. | 7, 8 |

Check the documents against the schemas:

```bash
opcp validate contract examples/quickstart/screen-name.yaml
opcp validate route examples/quickstart/screen-name.route.yaml
```

## 4. Change something and watch the control plane respond (4 minutes)

Try each of these in `quickstart.py`, one at a time:

- Remove the `evidence=` line from the adapter. A `check` must return evidence, so the call now fails instead of returning `ok`.
- Set `approved=False` in the supplier profile. The supplier is no longer eligible (spec 9.1(1)).
- In the route file, make `approved_by` the same person as `authored_by`. The route is refused (maker-checker).
- Change `rclass: R0` to `rclass: R2` in the contract. The gate now needs approval or a pre-approved budget, and none is configured, so the call is rejected before any supplier runs (spec 10).

## 5. Check your adapter (2 minutes)

```python
from opcp.conformance import check_adapter
print(check_adapter(adapter, contract).render())
```

This runs every example in the contract through the adapter. It checks that output matches the contract and its archetype, that evidence is present where required, and that a repeated idempotency key does not repeat the effect. It calls the supplier, so point it at a test environment.

## Next

- [ARCHITECTURE.md](ARCHITECTURE.md): how the parts fit, and what OPCP is not.
- [ADAPTERS.md](ADAPTERS.md): writing an adapter for a real supplier.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md): common errors and what they mean.
- The Exit-Readiness Scorecard, which needs no code: see the [README](../README.md).

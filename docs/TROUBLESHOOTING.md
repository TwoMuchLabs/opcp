# Troubleshooting

Messages below are the reference runtime's, quoted from the code. The response `status` is `rejected` when the authority gate (or an idempotency rule) stopped the call, and `failed` otherwise.

## Installing and running

| Symptom | Cause and fix |
|---|---|
| `opcp: command not found` | The scripts folder isn't on your `PATH`. Use `python -m opcp …` instead. |
| `ImportError: jsonschema cannot check the date-time … format(s)` | A dependency is missing (only after #39 merges). Reinstall with `pip install opcp`. |
| `… already exists. Use --force to overwrite.` | OPCP never overwrites your files silently. Pass `--force`, or choose another output path. |

## Building a control plane (`ConfigurationError`, `ValidationFailed`)

| Message | Meaning |
|---|---|
| `approved_by must differ from authored_by (maker-checker)` | A route must be approved by a second person (spec 9). |
| `route for '…' has no contract` | A route names a capability with no loaded contract. |
| `route for '…' names unknown adapter '…'` | A route lists an adapter id that wasn't passed to `ControlPlane`. |
| `adapter '…' fulfils '…', not '…'` | The adapter's profile is for a different capability than the route. |
| `concentration limit …% breached: …` | One supplier is primary for too many critical routes (spec 9.4). Record an approved `concentration_exception` on the routes, or change the routes. |
| `weights: '…' is not a candidate` | A weighted route weights an adapter that isn't in `candidates`. |

## Calls

| `status` and message | Meaning |
|---|---|
| `rejected` · `no contract for '…'; treated as R4` | The capability has no contract, so it fails closed (spec 10.2). Check the capability id. |
| `rejected` · `… requires approval and no approver is configured` | The class needs approval (R2 without budget, R3, R4). Configure an approver or an R2 budget on the `AuthorityGate`. |
| `rejected` · `R4 requires a second, different approver` | Two-person R4 is on and the approver didn't give a second, different person. |
| `rejected` · `idempotency key already used for a different input` | Same key, different payload. Use a new key for a new request. |
| `failed` · `no accountable human role named for this step (spec 10.5)` | Pass `accountable_role=…` on the call. The reference runtime requires it on every call. |
| `failed` · `input is …; contract accepts at most …` | The declared classification exceeds the contract's. |
| `failed` · `…: fails '…' rule` | The input doesn't match the contract's input schema. Values are left out of messages unless the deployment stores values. |
| `failed` · `no eligible supplier: …` | Every candidate failed an eligibility filter; the reasons follow (see below). |
| `failed` · `…: invalid output (…)` | The supplier's output failed the contract schema, the archetype's fields or the evidence requirement. See [ADAPTERS.md](ADAPTERS.md). |
| `failed` · `…: error (…)` | The adapter raised. With values off, only the exception type is logged. |
| `failed` · `best_score routing is not allowed for … capabilities (spec 9.3)` | `best_score` is limited to R0 and R1. |

## Why a supplier was excluded (spec 9.1)

| Reason | Fix |
|---|---|
| `not approved in the third-party register` | `approved=True` in the profile, once it is approved. |
| `supplier contract ended …` | Update `contract_end`, or remove the supplier from routes. |
| `has not passed conformance for contract v…` | Run `check_adapter`, and set `conformance_passed=True` and the right `contract_major`. |
| `not permitted to process … data` | The request's classification is above the profile's `max_data_classification`. |
| `processing regions not declared` | The request restricts residency and the profile has no `regions`. |
| `processes data outside permitted regions (…)` | The supplier processes in a region the request doesn't allow. An empty `residency` list allows none. |
| `not authorised for … actions (max …)` | The applied class, including any override, is above the profile's `max_rclass`. |
| `unhealthy or at capacity` | The adapter's `healthy()` returned false. |

Each exclusion is recorded in the event log's `route` entry, so `opcp ocel` and log exports show why a supplier wasn't used.

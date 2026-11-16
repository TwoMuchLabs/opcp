# Opening the event log in process-mining tools

OPCP's event log records every request, authority decision, routing choice, supplier attempt and response. `opcp ocel` converts an exported log to [OCEL 2.0](https://www.ocel-standard.org/) JSON, the object-centric event-log format that process-mining tools read. You can then see how work actually flows across capabilities and suppliers: where requests escalate to people, which suppliers fail over, and how often the gate stops an action.

```bash
# from Python: plane.log.export_jsonl("events.jsonl")
opcp ocel events.jsonl -o events.ocel.json
```

## What is in the export

| OCEL objects | One per | Linked to |
|---|---|---|
| `request` | request (trace) | its capability (`for`) and process (`in`) |
| `capability` | capability contract | – |
| `process` | process | – |
| `supplier` | supplier adapter | – |

| OCEL event | From log entry | Attributes | Links beyond request, capability, process |
|---|---|---|---|
| Request received | `request` | count of leased and withheld fields | – |
| Authority gate decided | `gate` | allowed, Reversibility Class, decision, accountable role | – |
| Route chosen | `route` | mode, route version, reason, number excluded | `candidate`, `excluded supplier` |
| Supplier attempted | `attempt` | outcome, confidence | `attempted supplier` |
| Response returned | `response` | status, Reversibility Class, latency, cost, error | `served by` |
| Replay served | `replay` | – | – |
| Shadow compared | `shadow` | outcome, fields agreed and disagreed | `shadow supplier`, `live supplier` |

## Privacy

The export holds only what the log holds. With values off, which is the runtime's default, the log records field names and counts, never input or output values, and so does the export. Check what your deployment records before sharing an export outside the firm.

## Checked with

The export was read with PM4Py's OCEL 2.0 JSON reader (`pm4py.read_ocel2_json`), version 2.7.23.11, on the demo log: 25 events, 18 objects and 91 event-to-object links. PM4Py is licensed under AGPL-3.0, so OPCP does not depend on it. Install it separately if you want to use it.

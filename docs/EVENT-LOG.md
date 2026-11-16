# The event log

The event log is the business's record of every request, authority decision, route and response (spec section 11.1). The reference runtime writes it as JSON Lines, one entry per line. By default, input values are left out and only field names are kept.

## Tamper evidence (optional)

The specification says entries must not be modified after they are written, but nothing in a plain JSON Lines file lets an auditor check that. The reference runtime can chain the log so that changes can be detected. This is opt-in while the specification change is discussed in issue #33.

```python
from opcp.eventlog import EventLog
from opcp.runtime import ControlPlane

log = EventLog("events.jsonl", chain=True)
plane = ControlPlane(contracts, adapters, routes, log=log)
...
head = log.head()   # keep this somewhere other than the log file
```

Each entry then carries `prev_hash`: the SHA-256 of the previous line exactly as written. The first entry uses 64 zeros. To check a file:

```bash
opcp log verify events.jsonl --head <head>
```

| Change to the file | Detected by `opcp log verify` |
|---|---|
| An entry edited | Yes, at the line after it |
| An entry inserted, removed or moved | Yes |
| Entries removed from the end | Only with `--head`, using a head kept elsewhere |
| The whole file replaced by a re-chained forgery | Only with `--head` |

So the head hash is what makes the chain worth having. Record it periodically somewhere the log's writer can't change: a register, a ticket, a timestamping service or a separate store. The chain is tamper *evidence*, not tamper *proofing*: it shows that something changed, not who changed it.

Verification hashes the exact bytes of each line, so it needs no canonical JSON form. Verify the file as exported, without reformatting it.

Chained logs convert to OCEL 2.0 like any other (`opcp ocel`, see [PROCESS-MINING.md](PROCESS-MINING.md)).

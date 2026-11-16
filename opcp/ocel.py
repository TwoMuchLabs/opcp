"""Export the event log as an OCEL 2.0 object-centric event log (JSON), for process-mining tools.

OCEL 2.0 (ocel-standard.org) records events that each relate to several objects, which fits OPCP's
log: one request touches a capability, a process, an authority decision and one or more suppliers.

Mapping
- Objects: ``request`` (one per trace), ``capability``, ``process`` and ``supplier`` (one per adapter).
  Each request relates to its capability ("for") and process ("in").
- Events: one per log entry. ``request`` becomes "Request received", ``gate`` "Authority gate decided",
  ``route`` "Route chosen", ``attempt`` "Supplier attempted", ``response`` "Response returned",
  ``replay`` "Replay served" and ``shadow`` "Shadow compared". Every event relates to its request,
  capability and process; supplier events also relate to the supplier, with a qualifier saying how.

Only what the log already holds is exported. With values off (the default), the log holds field
names, not values, and so does the export.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

EVENT_TYPES = {
    "request": "Request received",
    "gate": "Authority gate decided",
    "route": "Route chosen",
    "attempt": "Supplier attempted",
    "response": "Response returned",
    "replay": "Replay served",
    "shadow": "Shadow compared",
}


def _type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    return "string"


def _event_attributes(e: Mapping[str, Any]) -> dict[str, Any]:
    kind = e["kind"]
    if kind == "request":
        return {"leased_fields": len(e.get("leased_fields", [])), "withheld_fields": len(e.get("withheld_fields", []))}
    if kind == "gate":
        return {k: e[k] for k in ("allowed", "rclass", "decision", "accountable_role") if e.get(k) is not None}
    if kind == "route":
        return {"mode": e.get("mode"), "route_version": e.get("route_version"), "reason": e.get("reason"),
                "excluded_suppliers": len(e.get("excluded", {}))}
    if kind == "attempt":
        out = {"outcome": e.get("outcome")}
        if isinstance(e.get("confidence"), (int, float)):
            out["confidence"] = float(e["confidence"])
        return out
    if kind == "response":
        r = e.get("response", {})
        out = {"status": r.get("status"), "rclass": r.get("rclass")}
        if isinstance(r.get("latency_ms"), (int, float)):
            out["latency_ms"] = float(r["latency_ms"])
        cost = r.get("cost") or {}
        if isinstance(cost.get("amount"), (int, float)):
            out["cost"] = float(cost["amount"])
            out["currency"] = cost.get("currency")
        if r.get("error"):
            out["error"] = r["error"]
        return out
    if kind == "shadow":
        out = {"outcome": e.get("outcome")}
        if "agreed" in e:
            out["fields_agreed"] = len(e.get("agreed", []))
            out["fields_disagreed"] = len(e.get("disagreed", []))
        if e.get("reason"):
            out["reason"] = e["reason"]
        return out
    return {}


def to_ocel(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build an OCEL 2.0 JSON document from OPCP event-log entries."""
    entries = list(entries)
    context: dict[str, dict[str, str]] = {}  # trace -> capability, process
    for e in entries:
        if e.get("kind") == "request":
            req = e.get("request", {})
            context[e["trace_id"]] = {"capability": (req.get("capability") or {}).get("id", ""),
                                      "process": (req.get("process") or {}).get("id", ""),
                                      "step": (req.get("process") or {}).get("step", ""),
                                      "data_classification": req.get("data_classification", ""),
                                      "version": (req.get("capability") or {}).get("version", ""),
                                      "at": e["at"]}

    objects: dict[str, dict[str, Any]] = {}

    def obj(oid: str, otype: str, attrs: Mapping[str, Any] | None = None, at: str = "1970-01-01T00:00:00Z") -> str:
        if oid not in objects:
            objects[oid] = {"id": oid, "type": otype,
                            "attributes": [{"name": k, "time": at, "value": v} for k, v in (attrs or {}).items() if v != ""],
                            "relationships": []}
        return oid

    for trace, c in context.items():
        cap = obj(f"capability:{c['capability']}", "capability", {"version": c["version"]}, c["at"]) if c["capability"] else None
        proc = obj(f"process:{c['process']}", "process", {}, c["at"]) if c["process"] else None
        req = obj(f"request:{trace}", "request", {"step": c["step"], "data_classification": c["data_classification"]}, c["at"])
        if cap:
            objects[req]["relationships"].append({"objectId": cap, "qualifier": "for"})
        if proc:
            objects[req]["relationships"].append({"objectId": proc, "qualifier": "in"})

    events: list[dict[str, Any]] = []
    served: dict[str, str] = {}  # trace -> adapter whose attempt succeeded
    for n, e in enumerate(entries):
        kind = e.get("kind")
        if kind not in EVENT_TYPES:
            continue
        trace = e.get("trace_id", "")
        rels: list[dict[str, str]] = []
        if f"request:{trace}" in objects:
            rels.append({"objectId": f"request:{trace}", "qualifier": "request"})
            c = context[trace]
            if c["capability"]:
                rels.append({"objectId": f"capability:{c['capability']}", "qualifier": "capability"})
            if c["process"]:
                rels.append({"objectId": f"process:{c['process']}", "qualifier": "process"})
        if kind == "attempt" and e.get("adapter"):
            rels.append({"objectId": obj(f"supplier:{e['adapter']}", "supplier"), "qualifier": "attempted supplier"})
            if e.get("outcome") == "ok":
                served[trace] = e["adapter"]
        elif kind == "route":
            for aid in e.get("order", []):
                rels.append({"objectId": obj(f"supplier:{aid}", "supplier"), "qualifier": "candidate"})
            for aid in e.get("excluded", {}):
                rels.append({"objectId": obj(f"supplier:{aid}", "supplier"), "qualifier": "excluded supplier"})
        elif kind == "response" and trace in served:
            rels.append({"objectId": f"supplier:{served[trace]}", "qualifier": "served by"})
        elif kind == "shadow":
            if e.get("adapter"):
                rels.append({"objectId": obj(f"supplier:{e['adapter']}", "supplier"), "qualifier": "shadow supplier"})
            if e.get("live_adapter"):
                rels.append({"objectId": obj(f"supplier:{e['live_adapter']}", "supplier"), "qualifier": "live supplier"})
        attrs = {k: v for k, v in _event_attributes(e).items() if v is not None}
        events.append({"id": f"e{n + 1}", "type": EVENT_TYPES[kind], "time": e["at"],
                       "attributes": [{"name": k, "value": v} for k, v in attrs.items()],
                       "relationships": rels})

    def declared(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        types: dict[str, dict[str, str]] = {}
        for item in items:
            t = types.setdefault(item["type"], {})
            for a in item["attributes"]:
                t.setdefault(a["name"], _type(a["value"]))
        return [{"name": name, "attributes": [{"name": k, "type": v} for k, v in sorted(attrs.items())]}
                for name, attrs in sorted(types.items())]

    for o in objects.values():  # OCEL tools expect lists, even when empty
        o.setdefault("relationships", [])
    return {
        "objectTypes": declared(list(objects.values())) or [],
        "eventTypes": declared(events) or [],
        "objects": list(objects.values()),
        "events": events,
    }


def export_file(path: str | Path) -> str:
    """Read an exported OPCP event log (JSON lines) and return OCEL 2.0 JSON text."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines if line.strip()]
    return json.dumps(to_ocel(entries), indent=1, ensure_ascii=False)

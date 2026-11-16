"""OCEL 2.0 export of the event log."""

import json

from opcp.cli import main
from opcp.demo import run
from opcp.ocel import EVENT_TYPES, to_ocel


def demo_entries():
    return run(out=lambda *a, **k: None).log.entries()


def test_demo_log_converts_with_every_link_resolving():
    entries = demo_entries()
    doc = to_ocel(entries)
    assert set(doc) == {"objectTypes", "eventTypes", "objects", "events"}
    assert len(doc["events"]) == sum(1 for e in entries if e["kind"] in EVENT_TYPES)
    ids = {o["id"] for o in doc["objects"]}
    for ev in doc["events"]:
        assert ev["time"] and ev["type"] in EVENT_TYPES.values()
        assert all(r["objectId"] in ids for r in ev["relationships"])
    for o in doc["objects"]:
        assert all(r["objectId"] in ids for r in o["relationships"])
    assert {t["name"] for t in doc["objectTypes"]} == {"request", "capability", "process", "supplier"}


def test_attribute_types_are_declared_for_every_value():
    doc = to_ocel(demo_entries())
    declared = {t["name"]: {a["name"]: a["type"] for a in t["attributes"]} for t in doc["eventTypes"]}
    for ev in doc["events"]:
        for a in ev["attributes"]:
            assert a["name"] in declared[ev["type"]]
    assert declared["Authority gate decided"]["allowed"] == "boolean"
    assert declared["Supplier attempted"]["confidence"] == "float"


def test_requests_link_to_capability_and_process_and_responses_to_the_supplier():
    doc = to_ocel(demo_entries())
    req = next(o for o in doc["objects"] if o["type"] == "request")
    assert {r["qualifier"] for r in req["relationships"]} == {"for", "in"}
    served = [r for ev in doc["events"] if ev["type"] == "Response returned"
              for r in ev["relationships"] if r["qualifier"] == "served by"]
    assert served and all(r["objectId"].startswith("supplier:") for r in served)


def test_no_input_values_leave_through_the_export():
    text = json.dumps(to_ocel(demo_entries()))
    for secret in ("K1234567", "Alex Tan", "marketing"):  # demo inputs and a withheld field
        assert secret not in text


def test_shadow_entries_map_to_both_suppliers():
    entries = [
        {"at": "2026-10-25T01:00:00+00:00", "kind": "request", "trace_id": "t1",
         "request": {"capability": {"id": "verify-identity", "version": "1.0.0"}, "process": {"id": "onboarding", "step": "idv"},
                     "data_classification": "confidential"}},
        {"at": "2026-10-25T01:00:01+00:00", "kind": "shadow", "trace_id": "t1", "capability": "verify-identity",
         "adapter": "vendor-b", "live_adapter": "vendor-a", "outcome": "ok", "agreed": ["verdict"], "disagreed": ["reason_codes"]},
    ]
    (_, ev) = to_ocel(entries)["events"]
    assert ev["type"] == "Shadow compared"
    assert {(r["qualifier"], r["objectId"]) for r in ev["relationships"]} >= {
        ("shadow supplier", "supplier:vendor-b"), ("live supplier", "supplier:vendor-a")}
    assert {"name": "fields_disagreed", "value": 1} in ev["attributes"]


def test_cli(tmp_path, capsys):
    log = tmp_path / "events.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in demo_entries()))
    out = tmp_path / "events.ocel.json"
    assert main(["ocel", str(log), "-o", str(out)]) == 0
    assert json.loads(out.read_text())["events"]
    assert main(["ocel", str(log), "-o", str(out)]) == 1
    assert main(["ocel", str(log), "-o", str(out), "--force"]) == 0

"""Shadow routing for swap drills (spec 9.6)."""

import datetime as dt
import json
import threading
import time

import pytest

from opcp._io import ValidationFailed
from opcp._paths import data_dir
from opcp.adapter import Adapter, AdapterResult, SupplierProfile
from opcp.cli import main
from opcp.contract import load_catalogue
from opcp.demo import TODAY
from opcp.drill import load_jsonl, render_text, summarise
from opcp.eventlog import EventLog
from opcp.gate import AuthorityGate
from opcp.rclass import RClass
from opcp.router import Route, ShadowSpec
from opcp.runtime import ConfigurationError, ControlPlane

CATALOGUE = load_catalogue(data_dir("catalogue"))
PERSON = {"full_name": "Alex Tan", "date_of_birth": "1990-04-12",
          "document": {"type": "passport", "number": "K1234567", "issuing_country": "SG"},
          "marketing_notes": "not part of the contract"}
CALL = dict(process_id="onboarding", step="idv", principal="agent", data_classification="confidential",
            accountable_role="Head of Onboarding")


class Check(Adapter):
    def __init__(self, profile, verdict="pass", fail=False, bad=False, confidence=0.9):
        super().__init__(profile)
        self.verdict, self.fail, self.bad, self.confidence = verdict, fail, bad, confidence
        self.seen = []

    def invoke(self, payload, request):
        self.seen.append(dict(payload))
        if self.fail:
            raise RuntimeError("supplier down")
        output = {"verdict": "maybe"} if self.bad else {"verdict": self.verdict, "reason_codes": []}
        return AdapterResult(output, [{"type": "report", "reference": "r"}], self.confidence, 0.5)


def profile(aid, **kw):
    base = dict(adapter_id=aid, supplier_id=aid.upper(), kind="vendor", capability="verify-identity", contract_major=1,
                register_ref="TPR-1", approved=True, conformance_passed=True, max_data_classification="confidential",
                regions=frozenset({"SG"}), contract_end=dt.date(2030, 1, 1))
    base.update(kw)
    return SupplierProfile(**base)


def route(shadow, candidates=("live",), **kw):
    doc = {"opcp_version": "0.1", "capability": "verify-identity", "version": 1, "mode": "pinned",
           "authored_by": "maker", "approved_by": "checker", "candidates": list(candidates), **kw}
    if shadow is not None:
        doc["shadow"] = shadow
    return Route.from_dict(doc)


def setup(shadow_adapter, shadow=None, gate=None, **kw):
    live = Check(profile("live"))
    r = route(shadow or {"adapter": "alt"})
    log = EventLog()
    plane = ControlPlane(CATALOGUE, [live, shadow_adapter], [r], gate=gate, log=log, today=TODAY, **kw)
    return plane, live, log


def shadow_entries(plane):
    """Shadow calls run in the background: wait for them, then read what they recorded."""
    assert plane.wait_for_shadows(timeout=10)
    return [e for e in plane.log if e["kind"] == "shadow"]


def test_shadow_copies_the_leased_request_and_records_agreement():
    alt = Check(profile("alt"))
    plane, live, log = setup(alt)
    resp = plane.call("verify-identity", PERSON, idempotency_key="k1", **CALL)
    assert resp.status == "ok" and resp.supplier_id == "LIVE"
    assert alt.seen and "marketing_notes" not in alt.seen[0]  # only the leased fields leave
    (entry,) = shadow_entries(plane)
    assert entry["outcome"] == "ok" and entry["disagreed"] == []
    assert set(entry["agreed"]) >= {"verdict", "reason_codes"}
    assert "differences" not in entry  # values stay out of the log by default


def test_disagreement_is_recorded_and_never_changes_the_live_result():
    alt = Check(profile("alt"), verdict="refer")
    plane, _, log = setup(alt, store_values=True)
    resp = plane.call("verify-identity", PERSON, idempotency_key="k2", **CALL)
    assert resp.output["verdict"] == "pass"
    (entry,) = shadow_entries(plane)
    assert entry["disagreed"] == ["verdict"] or "verdict" in entry["disagreed"]
    assert entry["differences"]["verdict"] == {"live": "pass", "shadow": "refer"}


@pytest.mark.parametrize("kw, outcome", [({"fail": True}, "error"), ({"bad": True}, "invalid")])
def test_shadow_failures_are_recorded_and_the_live_call_succeeds(kw, outcome):
    alt = Check(profile("alt"), **kw)
    plane, _, log = setup(alt)
    assert plane.call("verify-identity", PERSON, idempotency_key="k3", **CALL).status == "ok"
    assert shadow_entries(plane)[0]["outcome"] == outcome


@pytest.mark.parametrize("kw, words", [
    ({"approved": False}, "not approved"),
    ({"regions": frozenset({"US"})}, "outside permitted regions"),
    ({"max_data_classification": "internal"}, "not permitted to process confidential"),
])
def test_ineligible_shadow_supplier_never_receives_data(kw, words):
    alt = Check(profile("alt", **kw))
    plane, _, log = setup(alt)
    plane.call("verify-identity", PERSON, idempotency_key="k4", residency=["SG"], **CALL)
    assert alt.seen == []
    (entry,) = shadow_entries(plane)
    assert entry["outcome"] == "skipped" and words in entry["reason"]


def test_shadow_never_runs_above_r0():
    alt = Check(profile("alt", max_rclass=RClass.R1))
    live = Check(profile("live", max_rclass=RClass.R1))
    gate = AuthorityGate(overrides={"verify-identity": RClass.R1})
    log = EventLog()
    plane = ControlPlane(CATALOGUE, [live, alt], [route({"adapter": "alt"})], gate=gate, log=log, today=TODAY)
    assert plane.call("verify-identity", PERSON, idempotency_key="k5", **CALL).status == "ok"
    assert alt.seen == []
    assert "only for R0" in shadow_entries(plane)[0]["reason"]


def test_replay_does_not_run_the_shadow_again():
    alt = Check(profile("alt"))
    plane, _, log = setup(alt)
    plane.call("verify-identity", PERSON, idempotency_key="k6", **CALL)
    plane.call("verify-identity", PERSON, idempotency_key="k6", **CALL)
    assert len(alt.seen) == 1 and len(shadow_entries(plane)) == 1


def test_sampling_is_deterministic_and_partial():
    spec = ShadowSpec("alt", sample=0.3)
    picks = [spec.selects(f"key-{i}") for i in range(1000)]
    assert picks == [spec.selects(f"key-{i}") for i in range(1000)]
    assert 200 < sum(picks) < 400


def test_compare_limits_the_fields_checked():
    alt = Check(profile("alt"), verdict="refer")
    plane, _, log = setup(alt, shadow={"adapter": "alt", "compare": ["reason_codes"]})
    plane.call("verify-identity", PERSON, idempotency_key="k7", **CALL)
    entry = shadow_entries(plane)[0]
    assert entry["agreed"] == ["reason_codes"] and entry["disagreed"] == []


def test_route_rules():
    with pytest.raises(ValidationFailed):
        route({"adapter": "live"})                      # the primary cannot shadow itself
    with pytest.raises(ValidationFailed):
        route({"adapter": "alt", "sample": 0})          # sample must be above zero
    with pytest.raises(ConfigurationError):
        ControlPlane(CATALOGUE, [Check(profile("live"))], [route({"adapter": "ghost"})], today=TODAY)


def test_drill_summary_and_cli(tmp_path, capsys):
    agree, differ = Check(profile("alt")), None
    plane, live, log = setup(agree)
    for i in range(4):
        person = {**PERSON, "document": {**PERSON["document"], "number": f"K{i:07d}"}}
        plane.call("verify-identity", person, idempotency_key=f"d{i}", **CALL)
    assert plane.wait_for_shadows(timeout=10)
    agree.verdict = "refer"
    agree._results.clear()
    plane.call("verify-identity", {**PERSON, "full_name": "Sam Lee"}, idempotency_key="d9", **CALL)
    assert plane.wait_for_shadows(timeout=10)
    (s,) = summarise(log)
    assert (s.compared, s.full_agreement) == (5, 4)
    assert s.to_dict()["field_agreement"]["verdict"] == pytest.approx(0.8)
    assert "full agreement 4 (80.0%)" in render_text([s])

    path = log.export_jsonl(tmp_path / "events.jsonl")
    assert summarise(load_jsonl(path))[0].compared == 5
    assert main(["shadow-report", str(path)]) == 0
    assert "shadow supplier alt" in capsys.readouterr().out
    assert main(["shadow-report", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["full_agreement"] == 4


def test_an_empty_event_log_passed_in_is_the_one_used():
    # Regression: an empty EventLog is falsy, and `log or EventLog()` silently replaced it.
    log = EventLog()
    plane = ControlPlane(CATALOGUE, [Check(profile("live"))], [route(None)], log=log, today=TODAY)
    assert plane.log is log


# ---------------------------------------------------------------- review of 7 Nov: timing, isolation, lease


class Slow(Check):
    def __init__(self, profile, delay, **kw):
        super().__init__(profile, **kw)
        self.delay = delay

    def invoke(self, payload, request):
        time.sleep(self.delay)
        return super().invoke(payload, request)


def test_a_slow_shadow_adds_nothing_to_the_live_call():
    alt = Slow(profile("alt"), delay=1.0)
    plane, _, _ = setup(alt)
    started = time.perf_counter()
    resp = plane.call("verify-identity", PERSON, idempotency_key="t1", **CALL)
    elapsed = time.perf_counter() - started
    assert resp.status == "ok" and elapsed < 0.5, elapsed  # before: +1.0 s, the shadow ran inline
    (entry,) = shadow_entries(plane)
    assert entry["outcome"] == "ok" and entry["latency_ms"] >= 900


def test_a_shadow_whose_forget_raises_cannot_fail_the_live_call():
    class BadForget(Check):
        def forget(self, payload, request):
            raise RuntimeError("cache unavailable")

    alt = BadForget(profile("alt"), bad=True)
    plane, _, _ = setup(alt)
    assert plane.call("verify-identity", PERSON, idempotency_key="t2", **CALL).status == "ok"
    outcomes = [e["outcome"] for e in shadow_entries(plane)]
    assert outcomes[0] == "invalid"  # recorded before forget() ran


def test_a_shadow_that_breaks_the_comparison_is_recorded_not_raised():
    class Explodes(dict):
        def get(self, *args):  # anything reading the output fails
            raise RuntimeError("unreadable output")

    class Odd(Check):
        def invoke(self, payload, request):
            result = super().invoke(payload, request)
            result.output = Explodes(result.output)
            return result

    alt = Odd(profile("alt"))
    plane, _, _ = setup(alt)
    assert plane.call("verify-identity", PERSON, idempotency_key="t3", **CALL).status == "ok"
    (entry,) = shadow_entries(plane)
    assert entry["outcome"] == "error" and entry["detail"] == "RuntimeError"


def test_the_shadow_entry_records_lent_and_withheld_fields():
    alt = Check(profile("alt"))
    plane, _, _ = setup(alt)
    plane.call("verify-identity", PERSON, idempotency_key="t4", **CALL)
    (entry,) = shadow_entries(plane)
    assert entry["withheld_fields"] == ["marketing_notes"]
    assert set(entry["leased_fields"]) == {"full_name", "date_of_birth", "document"}


def test_the_caller_changing_its_objects_cannot_change_what_the_shadow_receives():
    gate = threading.Event()

    class Waits(Check):
        def invoke(self, payload, request):
            gate.wait(5)
            return super().invoke(payload, request)

    alt = Waits(profile("alt"))
    plane, _, _ = setup(alt)
    person = json.loads(json.dumps(PERSON))
    resp = plane.call("verify-identity", person, idempotency_key="t5", **CALL)
    person["full_name"] = "Changed After Return"
    resp.output["verdict"] = "fail"
    gate.set()
    (entry,) = shadow_entries(plane)
    assert alt.seen[0]["full_name"] == "Alex Tan" and entry["disagreed"] == []


def test_close_waits_for_outstanding_shadows():
    alt = Slow(profile("alt"), delay=0.2)
    plane, _, log = setup(alt)
    plane.call("verify-identity", PERSON, idempotency_key="t6", **CALL)
    plane.close()
    assert [e["outcome"] for e in log if e["kind"] == "shadow"] == ["ok"]


def test_a_slow_shadow_supplier_cannot_pile_up_work_without_limit():
    # Red-team round 2: pending shadow calls (each holding a copy of leased data) grew with every request.
    gate = threading.Event()

    class Stuck(Check):
        def invoke(self, payload, request):
            gate.wait(10)
            return super().invoke(payload, request)

    alt = Stuck(profile("alt"))
    plane, _, log = setup(alt, shadow_queue_limit=5)
    for i in range(20):
        assert plane.call("verify-identity", {**PERSON, "full_name": f"P{i}"}, idempotency_key=f"q{i}", **CALL).ok
    assert len(plane._shadow_pending) <= 5
    gate.set()
    entries = shadow_entries(plane)
    full = [e for e in entries if e["outcome"] == "skipped" and "queue full" in e["reason"]]
    assert len(full) == 15 and sum(e["outcome"] == "ok" for e in entries) == 5

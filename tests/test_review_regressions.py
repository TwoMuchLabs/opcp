"""One test per issue found in the independent pre-publication review."""

import datetime as dt

import pytest

from opcp._io import ValidationFailed
from opcp.adapter import Adapter, AdapterResult, SupplierProfile
from opcp.cli import main
from opcp.conformance import check_runtime
from opcp.gate import AuthorityGate
from opcp.rclass import RClass
from opcp.router import Route
from opcp.runtime import ControlPlane
from opcp.scorecard import evaluate

from test_runtime import CALL, CATALOGUE, PERSON, TODAY, Fixed, plane, profile, route
from test_scorecard_and_conformance import EXAMPLE, proc

JOURNAL = {"entry_date": "2026-10-31", "currency": "SGD",
           "lines": [{"account": "1", "debit": 1, "credit": 0}, {"account": "2", "debit": 0, "credit": 1}]}


class Ledger(Adapter):
    def __init__(self, p, fail=False):
        super().__init__(p)
        self.fail = fail

    def invoke(self, payload, request):
        if self.fail:
            raise RuntimeError("ledger down for account 4410")
        return AdapterResult({"receipt_id": "r", "status": "completed", "compensation": "reverse r"}, [{"type": "a", "reference": "b"}])


def ledger_profile(**kw):
    return profile("l", capability="post-journal-entry", max_rclass=RClass.R2, max_data_classification="internal", **kw)


def journal_route(mode="pinned"):
    return Route.from_dict({"opcp_version": "0.1", "capability": "post-journal-entry", "version": 1, "mode": mode,
                            "authored_by": "m", "approved_by": "c", "candidates": ["l"]})


JCALL = dict(process_id="close", step="s", principal="u", data_classification="internal", accountable_role="Controller")


def test_idempotency_key_is_scoped_to_capability():
    p = ControlPlane(CATALOGUE, [Fixed(profile("a")), Ledger(ledger_profile())], [route(["a"]), journal_route()],
                     gate=AuthorityGate(budgets={"post-journal-entry": 1}), today=TODAY)
    assert p.call("verify-identity", PERSON, idempotency_key="same", **CALL).ok
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="same", **JCALL)
    assert r.ok and r.output["receipt_id"] == "r"


def test_reused_key_with_different_payload_is_refused():
    a = Fixed(profile("a"))
    p = plane([a], route(["a"]))
    assert p.call("verify-identity", PERSON, idempotency_key="k", **CALL).ok
    r = p.call("verify-identity", {**PERSON, "full_name": "Someone Else"}, idempotency_key="k", **CALL)
    assert r.status == "rejected" and a.invocations == 1


def test_gate_override_applies_to_routing():
    low = Fixed(profile("low", max_rclass=RClass.R0))
    p = ControlPlane(CATALOGUE, [low], [route(["low"])],
                     gate=AuthorityGate(overrides={"verify-identity": RClass.R3}, approver=lambda *a: __import__("opcp.gate").gate.Approval(True, by="x")),
                     today=TODAY)
    r = p.call("verify-identity", PERSON, idempotency_key="k", **CALL)
    assert r.status == "failed" and low.invocations == 0 and "not authorised for R3" in r.error


def test_lease_strips_nested_undeclared_fields():
    a = Fixed(profile("a"))
    p = plane([a], route(["a"]))
    doc = {**PERSON["document"], "mothers_maiden_name": "Lim"}
    r = p.call("verify-identity", {**PERSON, "document": doc}, idempotency_key="k", **CALL)
    assert r.ok and "mothers_maiden_name" not in a.seen[0]["document"]
    req = [e for e in p.log.entries(r.trace_id) if e["kind"] == "request"][0]
    assert req["withheld_fields"] == ["document.mothers_maiden_name"]


def test_rejection_is_not_cached_so_a_retry_can_succeed():
    from opcp.gate import Approval
    gate = AuthorityGate()
    p = ControlPlane(CATALOGUE, [Ledger(ledger_profile())], [journal_route()], gate=gate, today=TODAY)
    assert p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL).status == "rejected"
    gate.approver = lambda *a: Approval(True, by="controller")
    assert p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL).ok


def test_budget_refunded_when_call_fails():
    gate = AuthorityGate(budgets={"post-journal-entry": 1})
    p = ControlPlane(CATALOGUE, [Ledger(ledger_profile(), fail=True)], [journal_route()], gate=gate, today=TODAY)
    assert p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL).status == "failed"
    assert gate.budgets["post-journal-entry"] == 1


def test_cascade_can_end_with_human_candidate():
    low = Fixed(profile("low"), confidence=0.3)
    human = Fixed(profile("human", kind="human", register_ref=None), confidence=None)
    p = plane([low, human], route(["low", "human"], mode="cascade", cascade_min_confidence=0.99))
    r = p.call("verify-identity", PERSON, idempotency_key="k", **CALL)
    assert r.status == "escalated" and r.supplier_id == "HUMAN"


def test_segment_falls_back_to_default_candidates():
    bad = Fixed(profile("bad", approved=False))
    good = Fixed(profile("good"))
    p = plane([bad, good], route(["good"], mode="segmented", segments={"MY": ["bad"]}))
    assert p.call("verify-identity", PERSON, idempotency_key="k", segment="MY", **CALL).supplier_id == "GOOD"


def test_unknown_classification_and_failing_approver_do_not_crash():
    p = plane([Fixed(profile("a"))], route(["a"]))
    r = p.call("verify-identity", PERSON, idempotency_key="k", **{**CALL, "data_classification": "top-secret"})
    assert r.status == "failed" and "unknown data classification" in r.error

    def boom(*a):
        raise RuntimeError("approval service down")

    q = ControlPlane(CATALOGUE, [Ledger(ledger_profile())], [journal_route()], gate=AuthorityGate(approver=boom), today=TODAY)
    assert q.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL).status == "rejected"


def test_fail_closed_writes_gate_entry_and_role_is_required():
    p = plane([Fixed(profile("a"))], route(["a"]))
    r = p.call("nothing", {}, idempotency_key="k", **CALL)
    assert any(e["kind"] == "gate" for e in p.log.entries(r.trace_id))
    r = p.call("verify-identity", PERSON, idempotency_key="k2", **{**CALL, "accountable_role": None})
    assert r.status == "failed" and "accountable human role" in r.error


def test_stray_weights_and_missing_maker_rejected():
    with pytest.raises(ValidationFailed):
        route(["a"], mode="weighted", weights={"a": 1, "ghost": 1})
    with pytest.raises(ValidationFailed):
        Route.from_dict({"opcp_version": "0.1", "capability": "verify-identity", "version": 1, "mode": "pinned",
                         "approved_by": "c", "candidates": ["a"]})


def test_logs_do_not_leak_input_values():
    class Leaky(Adapter):
        def invoke(self, payload, request):
            raise RuntimeError(f"failed for {payload['full_name']}")

    p = plane([Leaky(profile("x"))], route(["x"]))
    p.call("verify-identity", {**PERSON, "full_name": "Very Private Name"}, idempotency_key="k", **CALL)
    bad = {**PERSON, "document": {**PERSON["document"], "issuing_country": "Singapore-XYZ"}}
    p.call("verify-identity", bad, idempotency_key="k2", **CALL)
    text = "\n".join(str(e) for e in p.log.entries())
    assert "Very Private Name" not in text and "Singapore-XYZ" not in text


def test_proven_requires_drill_date_and_expired_contract_flagged():
    with pytest.raises(ValidationFailed):
        evaluate(proc(time_to_swap={"contracting_days": 1, "onboarding_days": 1, "cutover_days": 1, "confidence": "proven"}))
    r = evaluate(proc(contract={"data_return": True, "termination_assistance": True, "notice_days": 30, "end_date": "2026-01-31"}))
    assert any("contract ended" in a for a in r.processes[0].actions)


def test_example_does_not_overwrite_and_errors_are_plain(tmp_path, capsys):
    path = tmp_path / "mine.yaml"
    path.write_text("my real work")
    assert main(["scorecard", "example", str(path)]) == 1 and path.read_text() == "my real work"
    assert main(["scorecard", "run", str(tmp_path / "missing.yaml")]) == 2
    broken = tmp_path / "broken.yaml"
    broken.write_text("organisation: [unclosed\n")
    assert main(["scorecard", "run", str(broken)]) == 2
    err = capsys.readouterr().err
    assert "File not found" in err and "not valid YAML" in err and "Traceback" not in err


def test_runtime_conformance_passes():
    report = check_runtime()
    assert report.passed, report.render()


def test_retry_after_failure_reaches_supplier_again():
    class Flaky(Adapter):
        def __init__(self, p):
            super().__init__(p)
            self.bad = True

        def invoke(self, payload, request):
            if self.bad:
                return AdapterResult({"verdict": "maybe"}, [{"type": "r", "reference": "x"}], 0.9)
            return AdapterResult({"verdict": "pass", "reason_codes": []}, [{"type": "r", "reference": "x"}], 0.9)

    a = Flaky(profile("a"))
    p = plane([a], route(["a"]))
    assert p.call("verify-identity", PERSON, idempotency_key="k", **CALL).status == "failed"
    a.bad = False
    assert p.call("verify-identity", PERSON, idempotency_key="k", **CALL).ok
    assert a.invocations == 2


def test_new_payload_after_failure_is_a_fresh_supplier_call():
    a = Fixed(profile("a"), bad=True)
    p = plane([a], route(["a"]))
    p.call("verify-identity", PERSON, idempotency_key="k", **CALL)
    a.bad = False
    other = {**PERSON, "full_name": "Other Person"}
    r = p.call("verify-identity", other, idempotency_key="k", **CALL)
    assert r.ok and a.seen[-1]["full_name"] == "Other Person"


def test_lease_fails_closed_for_free_form_and_composite_schemas():
    from opcp.contract import Contract
    doc = dict(CATALOGUE["verify-identity"].raw)
    doc["input"] = {"type": "object", "required": ["full_name"], "properties": {
        "full_name": {"type": "string"},
        "vars": {"type": "object"},
        "either": {"anyOf": [{"type": "string"}, {"type": "object"}]},
        "open": {"type": "object", "additionalProperties": True}}}
    c = Contract.from_dict(doc)
    leased, withheld = c.lease({"full_name": "A", "vars": {"ssn": "1"}, "either": {"ssn": "1"}, "open": {"k": "v"}})
    assert leased == {"full_name": "A", "vars": {}, "open": {"k": "v"}}
    assert "vars.ssn" in withheld and "either" in withheld


def test_an_empty_event_log_passed_in_is_the_one_used():
    # An empty EventLog is falsy, and `log or EventLog()` silently replaced it with a new one.
    from opcp.contract import load_catalogue
    from opcp.demo import TODAY
    from opcp.eventlog import EventLog
    from opcp.gate import AuthorityGate
    from opcp.runtime import ControlPlane
    from opcp._paths import data_dir

    log, gate = EventLog(), AuthorityGate()
    plane = ControlPlane(load_catalogue(data_dir("catalogue")), [], [], gate=gate, log=log, today=TODAY)
    assert plane.log is log and plane.gate is gate


def test_lowering_override_is_a_configuration_error():
    """Spec 10.1: a deployment may raise a class, never lower it. Caught when the control plane is built."""
    gate = AuthorityGate(overrides={"post-journal-entry": RClass.R0})
    with pytest.raises(Exception, match="may only raise"):
        ControlPlane(CATALOGUE, [Ledger(ledger_profile())], [journal_route()], gate=gate, today=TODAY)


def test_gate_error_fails_closed_and_is_logged():
    """Spec 10.2 and 10.6: if the gate cannot decide, nothing is invoked, the call is refused and the refusal is logged."""
    ledger = Ledger(ledger_profile())
    p = ControlPlane(CATALOGUE, [ledger], [journal_route()], gate=AuthorityGate(budgets={"post-journal-entry": 1}), today=TODAY)
    p.gate.overrides = {"post-journal-entry": RClass.R0}  # changed after construction
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert r.status == "rejected" and ledger.invocations == 0
    gate_entries = [e for e in p.log if e["kind"] == "gate"]
    assert len(gate_entries) == 1 and gate_entries[0]["allowed"] is False and gate_entries[0]["rclass"] == "R4"
    assert "ValueError" in gate_entries[0]["reason"] and "lower" not in gate_entries[0]["reason"]  # no detail unless values are stored
    p.gate.overrides = {}
    assert p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL).ok  # a refusal is not cached

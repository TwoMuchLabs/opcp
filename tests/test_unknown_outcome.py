"""Issue #27: after an attempt whose outcome is unknown, a call with a lasting effect never moves to another supplier.

A supplier that acts and then times out, or replies with output the runtime cannot accept, may have performed the
effect. Failing over would perform it again at a second supplier under the same idempotency key (spec 7.1).
"""

from __future__ import annotations

import datetime as dt
import json

from opcp._io import errors, validator_for
from opcp._paths import data_dir
from opcp.adapter import Adapter, AdapterResult, DefiniteFailure
from opcp.gate import Approval, AuthorityGate
from opcp.rclass import RClass
from opcp.router import Route
from opcp.runtime import ControlPlane, has_lasting_effect

from test_runtime import CALL, CATALOGUE, PERSON, TODAY, profile

JOURNAL = {"entry_date": "2026-10-31", "currency": "SGD",
           "lines": [{"account": "1", "debit": 1, "credit": 0}, {"account": "2", "debit": 0, "credit": 1}]}
JCALL = dict(process_id="close", step="s", principal="u", data_classification="internal", accountable_role="Controller")
RECEIPT = {"receipt_id": "r", "status": "completed", "compensation": "reverse r"}


class Ledger(Adapter):
    """A ledger that records every posting it makes, then behaves as scripted.

    ``then``: "ok" replies with a receipt; "timeout" posts and loses the reply; "invalid" posts and replies with a
    malformed receipt; "refuse" refuses before posting (a definite failure). ``script`` gives one value per call.
    """

    def __init__(self, p, *script: str, postings: list | None = None):
        super().__init__(p)
        self.script = list(script) or ["ok"]
        self.postings = postings if postings is not None else []

    def invoke(self, payload, request):
        then = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if then == "refuse":
            raise DefiniteFailure("account closed")
        self.postings.append(self.profile.supplier_id)
        if then == "timeout":
            raise TimeoutError("no reply")
        if then == "invalid":
            return AdapterResult({**RECEIPT, "receipt_id": 7}, [{"type": "gl", "reference": "g"}])
        return AdapterResult(dict(RECEIPT), [{"type": "gl", "reference": "g"}], confidence=0.5)


def lp(aid, **kw):
    kw.setdefault("max_rclass", RClass.R2)
    return profile(aid, capability="post-journal-entry", max_data_classification="internal", **kw)


def jroute(candidates, mode="pinned", **extra):
    return Route.from_dict({"opcp_version": "0.1", "capability": "post-journal-entry", "version": 1, "mode": mode,
                            "authored_by": "m", "approved_by": "c", "candidates": candidates, **extra})


def ledger_plane(adapters, route, budget=5, **kw):
    gate = AuthorityGate(budgets={"post-journal-entry": budget})
    return ControlPlane(CATALOGUE, adapters, [route], gate=gate, today=kw.pop("today", TODAY), **kw)


# ------------------------------------------------------------- the reported defect


def test_timeout_after_posting_does_not_fail_over():
    posted: list[str] = []
    p = ledger_plane([Ledger(lp("a"), "timeout", postings=posted), Ledger(lp("b"), postings=posted)], jroute(["a", "b"]))
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="k1", **JCALL)
    assert posted == ["A"]  # before the fix: ["A", "B"] and status ok
    assert r.status == "failed" and r.outcome == "unknown" and r.supplier_id == "A"
    assert "outcome unknown at a" in r.error and "no other supplier was tried" in r.error


def test_invalid_reply_after_posting_does_not_fail_over():
    posted: list[str] = []
    p = ledger_plane([Ledger(lp("a"), "invalid", postings=posted), Ledger(lp("b"), postings=posted)], jroute(["a", "b"]))
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="k1", **JCALL)
    assert posted == ["A"] and r.status == "failed" and r.outcome == "unknown" and r.output is None


def test_definite_failure_still_fails_over():
    posted: list[str] = []
    p = ledger_plane([Ledger(lp("a"), "refuse", postings=posted), Ledger(lp("b"), postings=posted)], jroute(["a", "b"]))
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="k1", **JCALL)
    assert r.ok and r.supplier_id == "B" and posted == ["B"] and r.outcome is None


def test_r0_check_still_fails_over_after_any_error():
    class Flaky(Adapter):
        def invoke(self, payload, request):
            raise TimeoutError("slow")

    class Good(Adapter):
        def invoke(self, payload, request):
            return AdapterResult({"verdict": "pass", "reason_codes": []}, [{"type": "report", "reference": "r"}], 0.9)

    route = Route.from_dict({"opcp_version": "0.1", "capability": "verify-identity", "version": 1, "mode": "pinned",
                             "authored_by": "m", "approved_by": "c", "candidates": ["a", "b"]})
    p = ControlPlane(CATALOGUE, [Flaky(profile("a")), Good(profile("b"))], [route], today=TODAY)
    r = p.call("verify-identity", PERSON, idempotency_key="k", **CALL)
    assert r.ok and r.supplier_id == "B"


# ------------------------------------------------------------- every way of moving on is closed


def test_segmented_route_does_not_fall_back():
    posted: list[str] = []
    route = jroute(["b"], mode="segmented", segments={"SG": ["a"]})
    p = ledger_plane([Ledger(lp("a"), "timeout", postings=posted), Ledger(lp("b"), postings=posted)], route)
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="k", segment="SG", **JCALL)
    assert r.outcome == "unknown" and posted == ["A"]


def test_weighted_route_does_not_move_to_the_rest():
    posted: list[str] = []
    route = jroute(["a", "b"], mode="weighted", weights={"a": 1.0})
    p = ledger_plane([Ledger(lp("a"), "timeout", postings=posted), Ledger(lp("b"), postings=posted)], route)
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert r.outcome == "unknown" and posted == ["A"]


def test_cascade_does_not_move_on_after_a_low_confidence_posting():
    posted: list[str] = []
    route = jroute(["a", "b"], mode="cascade", cascade_min_confidence=0.9)
    p = ledger_plane([Ledger(lp("a"), postings=posted), Ledger(lp("b"), postings=posted)], route)
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert r.outcome == "unknown" and posted == ["A"]


def test_no_escalation_after_an_unknown_outcome():
    posted: list[str] = []
    human = Ledger(lp("h", kind="human", register_ref=None), postings=posted)
    p = ledger_plane([Ledger(lp("a"), "timeout", postings=posted), human], jroute(["a"], escalation="h"))
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert r.outcome == "unknown" and posted == ["A"]


# ------------------------------------------------------------- budget and retries


def test_budget_unit_is_kept_after_an_unknown_outcome():
    p = ledger_plane([Ledger(lp("a"), "timeout")], jroute(["a"]), budget=1)
    assert p.call("post-journal-entry", JOURNAL, idempotency_key="k1", **JCALL).outcome == "unknown"
    assert p.gate.budgets["post-journal-entry"] == 0  # the supplier may have used it
    assert p.call("post-journal-entry", JOURNAL, idempotency_key="k2", **JCALL).status == "rejected"


def test_retry_goes_back_to_that_supplier_even_after_the_route_changes():
    posted: list[str] = []
    a, b = Ledger(lp("a"), "timeout", "ok", postings=posted), Ledger(lp("b"), postings=posted)
    p = ledger_plane([a, b], jroute(["a", "b"]))
    assert p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL).outcome == "unknown"
    p.routes["post-journal-entry"] = jroute(["b", "a"])  # B is now primary
    retry = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert retry.ok and retry.supplier_id == "A" and posted == ["A", "A"]


def test_retry_resolves_at_the_supplier_that_may_have_acted():
    posted: list[str] = []
    a, b = Ledger(lp("a"), "timeout", "ok", postings=posted), Ledger(lp("b"), postings=posted)
    p = ledger_plane([a, b], jroute(["a", "b"]))
    assert p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL).outcome == "unknown"
    retry = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert retry.ok and retry.supplier_id == "A" and "B" not in posted
    route = [e for e in p.log.entries(retry.trace_id) if e["kind"] == "route"][-1]
    assert route["order"][0] == "a" and "after an unknown outcome" in route["reason"]
    # Resolved: the key now replays the completed response.
    assert p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL).trace_id == retry.trace_id


def test_retry_fails_over_once_the_supplier_reports_it_did_nothing():
    posted: list[str] = []
    a, b = Ledger(lp("a"), "timeout", "refuse", postings=posted), Ledger(lp("b"), postings=posted)
    p = ledger_plane([a, b], jroute(["a", "b"]))
    p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    retry = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert retry.ok and retry.supplier_id == "B" and posted == ["A", "B"]


def test_retry_unknown_again_stays_unknown():
    posted: list[str] = []
    p = ledger_plane([Ledger(lp("a"), "timeout", postings=posted), Ledger(lp("b"), postings=posted)], jroute(["a", "b"]))
    p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    retry = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert retry.outcome == "unknown" and posted == ["A", "A"]


def test_key_stays_bound_to_its_input_after_an_unknown_outcome():
    p = ledger_plane([Ledger(lp("a"), "timeout"), Ledger(lp("b"))], jroute(["a", "b"]))
    p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    other = {**JOURNAL, "entry_date": "2026-11-01"}
    r = p.call("post-journal-entry", other, idempotency_key="k", **JCALL)
    assert r.status == "rejected" and r.route_reason == "idempotency"


def test_reserved_supplier_no_longer_eligible_is_not_replaced():
    posted: list[str] = []
    a = Ledger(lp("a", contract_end=dt.date(2026, 11, 30)), "timeout", postings=posted)
    p = ledger_plane([a, Ledger(lp("b"), postings=posted)], jroute(["a", "b"]), budget=2)
    p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    p.today = dt.date(2026, 12, 1)  # supplier A's contract has ended
    retry = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert retry.outcome == "unknown" and retry.supplier_id == "A" and posted == ["A"]
    assert "not eligible now" in retry.error and "contract ended" in retry.error
    assert p.gate.budgets["post-journal-entry"] == 1  # the retry reached no supplier, so its unit is refunded


# ------------------------------------------------------------- scope, envelope and log


def test_which_capabilities_have_a_lasting_effect():
    effects = {cid: has_lasting_effect(c, c.rclass) for cid, c in CATALOGUE.items()}
    assert effects == {"extract-document-fields": False, "post-journal-entry": True, "review-identity-exception": False,
                       "send-customer-notification": True, "verify-identity": False}
    # A deployment that raises a check to R2 makes it effectful too.
    assert has_lasting_effect(CATALOGUE["verify-identity"], RClass.R2)


def test_notify_does_not_fail_over_after_unknown_outcome():
    sent: list[str] = []

    class Sms(Adapter):
        def __init__(self, p, lose_reply):
            super().__init__(p)
            self.lose_reply = lose_reply

        def invoke(self, payload, request):
            sent.append(self.profile.supplier_id)
            if self.lose_reply:
                raise ConnectionResetError("reset")
            return AdapterResult({"message_id": "m", "delivery_status": "sent"}, [{"type": "sms", "reference": "s"}])

    def sp(aid):
        return profile(aid, capability="send-customer-notification", max_rclass=RClass.R4)

    route = Route.from_dict({"opcp_version": "0.1", "capability": "send-customer-notification", "version": 1,
                             "mode": "pinned", "authored_by": "m", "approved_by": "c", "candidates": ["a", "b"]})
    gate = AuthorityGate(approver=lambda *a: Approval(True, "ops lead"))
    p = ControlPlane(CATALOGUE, [Sms(sp("a"), True), Sms(sp("b"), False)], [route], gate=gate, today=TODAY)
    payload = {"recipient_ref": "C1", "channel": "sms", "template_id": "t1", "variables": {}}
    r = p.call("send-customer-notification", payload, idempotency_key="n", process_id="p", step="s",
               principal="u", data_classification="confidential", accountable_role="Ops")
    assert r.outcome == "unknown" and sent == ["A"]


def test_unknown_outcome_is_logged_and_the_envelope_validates():
    p = ledger_plane([Ledger(lp("a"), "timeout"), Ledger(lp("b"))], jroute(["a", "b"]))
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    kinds = [(e["kind"], e.get("outcome")) for e in p.log.entries(r.trace_id)]
    assert ("attempt", "unknown") in kinds and ("attempt", "ok") not in kinds
    doc = r.to_dict()
    assert doc["outcome"] == "unknown" and doc["supplier"]["id"] == "A"
    schema = json.loads((data_dir("schema") / "envelope.schema.json").read_text(encoding="utf-8"))
    assert not errors(validator_for({**schema, "$ref": "#/$defs/response"}), doc)


def test_a_definite_failure_on_retry_releases_the_key():
    posted: list[str] = []
    a = Ledger(lp("a", contract_end=dt.date(2026, 11, 30)), "timeout", "refuse", postings=posted)
    b = Ledger(lp("b"), "refuse", "ok", postings=posted)
    p = ledger_plane([a, b], jroute(["a", "b"]))
    assert p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL).outcome == "unknown"
    second = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert second.status == "failed" and second.outcome is None  # both definitely did nothing
    p.today = dt.date(2026, 12, 1)  # A is no longer eligible, and no longer holds the key
    third = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert third.ok and third.supplier_id == "B" and posted == ["A", "B"]


def test_unknown_outcome_at_the_escalation_supplier_is_reported():
    posted: list[str] = []
    human = Ledger(lp("h", kind="human", register_ref=None), "timeout", postings=posted)
    p = ledger_plane([Ledger(lp("a"), "refuse", postings=posted), human], jroute(["a"], escalation="h"))
    r = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert r.outcome == "unknown" and r.supplier_id == "H" and posted == ["H"]
    assert "a: error (DefiniteFailure)" in r.error


def test_reserved_adapter_removed_from_configuration_still_names_the_supplier():
    posted: list[str] = []
    p = ledger_plane([Ledger(lp("a"), "timeout", postings=posted), Ledger(lp("b"), postings=posted)], jroute(["a", "b"]))
    p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    del p.adapters["a"]  # the adapter was taken out of service
    p.routes["post-journal-entry"] = jroute(["b"])
    retry = p.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert retry.outcome == "unknown" and retry.supplier_id == "A" and posted == ["A"]
    assert "no longer configured" in retry.error


def test_schema_requires_failed_status_and_supplier_with_outcome():
    schema = json.loads((data_dir("schema") / "envelope.schema.json").read_text(encoding="utf-8"))
    validator = validator_for({**schema, "$ref": "#/$defs/response"})
    base = {"envelope_version": "0.1", "trace_id": "t", "latency_ms": 1, "rclass": "R2",
            "route": {"mode": "pinned", "reason": "r"}, "outcome": "unknown"}
    supplier = {"id": "A", "adapter_version": "1"}
    assert not errors(validator, {**base, "status": "failed", "supplier": supplier})
    assert errors(validator, {**base, "status": "failed"})  # who to reconcile with is required
    assert errors(validator, {**base, "status": "ok", "supplier": supplier, "output": {}})
    assert errors(validator, {**base, "status": "failed", "supplier": supplier, "outcome": "maybe"})

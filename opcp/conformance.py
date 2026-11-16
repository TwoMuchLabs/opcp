"""Adapter conformance (spec section 13)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .adapter import Adapter
from .contract import Contract
from .envelope import Request


@dataclass
class ConformanceReport:
    adapter_id: str
    capability: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(ok for _, ok, _ in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))

    def render(self) -> str:
        lines = [f"Conformance: {self.adapter_id} -> {self.capability}: {'PASS' if self.passed else 'FAIL'}"]
        for name, ok, detail in self.checks:
            lines.append(f"  [{'pass' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
        return "\n".join(lines)


def check_adapter(adapter: Adapter, contract: Contract) -> ConformanceReport:
    """Run every contract example through the adapter. Calls the supplier, so use a test environment."""
    report = ConformanceReport(adapter.profile.adapter_id, contract.id)
    report.add("adapter declares this capability", adapter.profile.capability == contract.id, adapter.profile.capability)
    report.add("adapter targets this contract major version", adapter.profile.contract_major == contract.major,
               f"adapter v{adapter.profile.contract_major}, contract v{contract.major}")
    for index, example in enumerate(contract.examples):
        label = example.get("name", f"example {index + 1}")
        leased, _ = contract.lease(example["input"])
        request = Request(contract.id, contract.version, "conformance", label, "conformance-runner", leased,
                          contract.data_classification, idempotency_key=f"conformance-{contract.id}-{index}")
        try:
            result = adapter.call(dict(leased), request)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            report.add(f"{label}: call succeeds", False, str(exc))
            continue
        problems = contract.output_errors(result.output)
        report.add(f"{label}: output matches contract and archetype", not problems, "; ".join(problems))
        if contract.evidence_required:
            report.add(f"{label}: evidence returned", bool(result.evidence))
        if result.confidence is not None:
            report.add(f"{label}: confidence within 0..1", 0 <= result.confidence <= 1, str(result.confidence))
        before = adapter.invocations
        again = adapter.call(dict(leased), request)
        report.add(f"{label}: repeated idempotency key does not repeat the effect",
                   adapter.invocations == before and again.output == result.output)
    return report


# ---------------------------------------------------------------- runtime conformance


class _Probe(Adapter):
    """A supplier that records what it receives and returns a valid result for its contract.

    It deliberately keeps no idempotency memory: the runtime under test must prevent repeats itself
    (spec 7.1). With the ``Adapter`` base class's memory, a runtime with no idempotency at all passed.
    """

    def call(self, payload, request):
        return self.invoke(payload, request)

    OUTPUTS = {
        "check": {"verdict": "pass", "reason_codes": []},
        "notify": {"message_id": "m-1", "delivery_status": "sent"},
        "transact": {"receipt_id": "r-1", "status": "completed", "compensation": "reverse r-1"},
    }

    def __init__(self, profile, archetype: str):
        super().__init__(profile)
        self.archetype = archetype
        self.received: list[dict] = []

    def invoke(self, payload, request):
        from .adapter import AdapterResult

        self.received.append(payload)
        return AdapterResult(dict(self.OUTPUTS[self.archetype]), [{"type": "probe", "reference": "p"}], 0.99, 0.0)


def check_runtime(factory=None) -> ConformanceReport:
    """Check that a runtime enforces spec section 13. ``factory`` builds a runtime with the same
    constructor as :class:`opcp.runtime.ControlPlane`; it must expose ``call`` and ``log``."""
    import datetime as dt

    from ._paths import data_dir
    from .adapter import SupplierProfile
    from .contract import load_catalogue
    from .gate import AuthorityGate
    from .rclass import RClass
    from .router import Route
    from .runtime import ControlPlane

    factory = factory or ControlPlane
    contracts = load_catalogue(data_dir("catalogue"))
    report = ConformanceReport("runtime", "spec section 13")
    today = dt.date(2026, 10, 24)

    def prof(aid, cap, **kw):
        base = dict(adapter_id=aid, supplier_id=aid, kind="vendor", capability=cap, contract_major=1, register_ref="TPR-x",
                    approved=True, conformance_passed=True, max_data_classification="confidential",
                    regions=frozenset({"SG"}), max_rclass=RClass.R4)
        base.update(kw)
        return SupplierProfile(**base)

    def route(cap, ids, mode="pinned", **kw):
        return Route.from_dict({"opcp_version": "0.1", "capability": cap, "version": 1, "mode": mode,
                                "authored_by": "maker", "approved_by": "checker", "candidates": ids, **kw})

    idv_ok = _Probe(prof("ok", "verify-identity"), "check")
    idv_unapproved = _Probe(prof("unapproved", "verify-identity", approved=False), "check")
    idv_offshore = _Probe(prof("offshore", "verify-identity", regions=frozenset({"US"})), "check")
    notify = _Probe(prof("notify", "send-customer-notification"), "notify")
    ledger = _Probe(prof("ledger", "post-journal-entry", max_data_classification="internal"), "transact")
    plane = factory(contracts, [idv_unapproved, idv_offshore, idv_ok, notify, ledger],
                    [route("verify-identity", ["unapproved", "offshore", "ok"]),
                     route("send-customer-notification", ["notify"]),
                     route("post-journal-entry", ["ledger"], mode="best_score")], today=today,
                    gate=AuthorityGate(budgets={"post-journal-entry": 5}))
    who = dict(process_id="conformance", step="s", principal="runner", accountable_role="Conformance owner")
    person = {"full_name": "A B", "date_of_birth": "1990-01-01",
              "document": {"type": "passport", "number": "X1", "issuing_country": "SG", "secret_note": "do not send"}}

    r = plane.call("send-customer-notification", {"recipient_ref": "C", "channel": "email", "template_id": "t"},
                   data_classification="confidential", idempotency_key="n1", **who)
    report.add("gate runs before any supplier (R4 without approval is rejected)", r.status == "rejected" and not notify.received)

    r = plane.call("verify-identity", person, data_classification="confidential", idempotency_key="i1", residency=["SG"], **who)
    report.add("ineligible suppliers are never called", r.status == "ok" and not idv_unapproved.received and not idv_offshore.received)
    report.add("context lease removes undeclared fields at every depth",
               bool(idv_ok.received) and "secret_note" not in idv_ok.received[0].get("document", {}))

    r = plane.call("post-journal-entry", {"entry_date": "2026-10-31", "currency": "SGD",
                                          "lines": [{"account": "1", "debit": 1, "credit": 0}, {"account": "2", "debit": 0, "credit": 1}]},
                   data_classification="internal", idempotency_key="j1", **who)
    gate_allowed = any(e["kind"] == "gate" and e["allowed"] for e in plane.log.entries(r.trace_id))
    report.add("best_score routing refused above R1 (after the gate allowed the call)",
               gate_allowed and r.status != "ok" and not ledger.received)

    r = plane.call("unknown-capability", {}, data_classification="internal", idempotency_key="u1", **who)
    report.add("unknown capability fails closed as R4", r.status == "rejected" and r.rclass == "R4")
    report.add("every call's gate decision is in the event log",
               all(any(e["kind"] == "gate" for e in plane.log.entries(t))
                   for t in {e["trace_id"] for e in plane.log.entries() if e["kind"] == "request"}))

    before = len(idv_ok.received)
    again = plane.call("verify-identity", person, data_classification="confidential", idempotency_key="i1", residency=["SG"], **who)
    report.add("repeated idempotency key does not repeat the effect", again.status == "ok" and len(idv_ok.received) == before)
    changed = plane.call("verify-identity", {**person, "full_name": "C D"}, data_classification="confidential",
                         idempotency_key="i1", residency=["SG"], **who)
    report.add("reused idempotency key with different input is refused", changed.status == "rejected" and len(idv_ok.received) == before)
    return report

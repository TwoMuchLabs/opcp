"""Run the language-neutral runtime fixtures in conformance/runtime/ against the reference ControlPlane.

This file is the reference implementation's *harness*: it turns a fixture's setup into contracts,
scripted suppliers, routes and an authority gate, makes the calls, and reports what an outside
observer can see. Another implementation writes its own harness for the same fixtures; nothing
here is part of the specification. The fixture format is documented in conformance/README.md.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from opcp._io import ValidationFailed
from opcp._paths import data_dir
from opcp.adapter import Adapter, AdapterResult, SupplierProfile
from opcp.contract import Contract, load_catalogue
from opcp.gate import Approval, AuthorityGate
from opcp.rclass import RClass
from opcp.router import Route
from opcp.runtime import ConfigurationError, ControlPlane

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = sorted((ROOT / "conformance" / "runtime").glob("*.json"))
CATALOGUE = load_catalogue(data_dir("catalogue"))

# Defaults for supplier fields a fixture leaves out (conformance/README.md, "Runtime fixtures").
SUPPLIER_DEFAULTS = {
    "kind": "vendor", "register_ref": "TPR-1", "approved": True, "conformance_passed": True,
    "contract_major": 1, "contract_end": "2030-01-01", "max_data_classification": "confidential",
    "regions": ["SG"], "max_rclass": "R0",
}
CALL_DEFAULTS = {"process_id": "p", "step": "s", "principal": "agent", "accountable_role": "Process owner"}


class Scripted(Adapter):
    """A supplier that does what the fixture says and records exactly what it received."""

    def __init__(self, profile: SupplierProfile, behaviour: dict):
        super().__init__(profile)
        self.behaviour = behaviour
        self.received: list[dict] = []

    def invoke(self, payload, request):
        self.received.append(json.loads(json.dumps(payload)))
        if self.behaviour.get("error"):
            raise RuntimeError("scripted definite failure")
        r = self.behaviour["respond"]
        return AdapterResult(r["output"], r.get("evidence", []), r.get("confidence"), r.get("cost"))


def build(setup: dict) -> ControlPlane:
    contracts = {}
    for item in setup["contracts"]:
        contract = CATALOGUE[item] if isinstance(item, str) else Contract.from_dict(item)
        contracts[contract.id] = contract
    adapters = []
    for s in setup["suppliers"]:
        f = {**SUPPLIER_DEFAULTS, **s}
        profile = SupplierProfile(
            adapter_id=f["adapter_id"], supplier_id=f["supplier_id"], kind=f["kind"], capability=f["capability"],
            contract_major=f["contract_major"], register_ref=f["register_ref"], approved=f["approved"],
            contract_end=dt.date.fromisoformat(f["contract_end"]) if f["contract_end"] else None,
            max_data_classification=f["max_data_classification"], regions=frozenset(f["regions"]),
            max_rclass=RClass.parse(f["max_rclass"]), conformance_passed=f["conformance_passed"],
        )
        adapters.append(Scripted(profile, f["behaviour"]))
    routes = [Route.from_dict(r) for r in setup.get("routes", [])]
    g = setup.get("gate", {})
    answers = [Approval(a["approved"], a.get("by"), a.get("second_by"), a.get("reason", "")) for a in g.get("approvals", [])]
    approver = (lambda request, contract, rclass, decision: answers.pop(0)) if "approvals" in g else None
    gate = AuthorityGate(budgets=dict(g.get("budgets", {})), approver=approver,
                         overrides={k: RClass.parse(v) for k, v in g.get("overrides", {}).items()},
                         two_person_r4=g.get("two_person_r4", False))
    return ControlPlane(contracts, adapters, routes, gate=gate, today=dt.date.fromisoformat(setup["today"]))


def observe(plane: ControlPlane, response) -> dict:
    """What the fixtures may assert about one call: envelope facts and whether a gate decision was recorded."""
    gate = [e for e in plane.log.entries(response.trace_id) if e["kind"] == "gate"]
    return {
        "status": response.status,
        "supplier": response.supplier_id,
        "rclass": response.rclass,
        "gate_decision": None if not gate else {"allowed": gate[-1]["allowed"], "rclass": gate[-1]["rclass"]},
    }


def test_runtime_suite_is_present():
    assert len(FIXTURES) >= 20


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_runtime_fixture(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert fixture["guarantee"] and fixture["id"] == path.stem
    try:
        plane = build(fixture["setup"])
    except (ConfigurationError, ValidationFailed, ValueError) as exc:
        assert fixture.get("expect_setup_rejected"), f"setup rejected unexpectedly: {exc}"
        return
    assert not fixture.get("expect_setup_rejected"), "setup should have been rejected"

    for i, call in enumerate(fixture["calls"]):
        args = {**CALL_DEFAULTS, **{k: v for k, v in call.items() if k not in ("capability", "input", "expect")}}
        response = plane.call(call["capability"], call["input"], **args)
        seen = observe(plane, response)
        for key, expected in call["expect"].items():
            assert seen[key] == expected, (fixture["guarantee"], f"call {i}: {key}", seen)

    final = fixture.get("expect_final", {})
    for aid, n in final.get("invocations", {}).items():
        assert plane.adapters[aid].invocations == n, (fixture["guarantee"], f"{aid} invocations")
    for aid, payloads in final.get("received", {}).items():
        assert plane.adapters[aid].received == payloads, (fixture["guarantee"], f"{aid} received")

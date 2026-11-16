"""Two-person approval and approver names (red-team R2-02, spec 10.4)."""

import pytest

from opcp.gate import AuthorityGate

from test_runtime import CATALOGUE

@pytest.mark.parametrize("by, second", [("alice", "Alice"), ("alice", "alice "), ("Alice  Tan", "alice tan"),
                                        ("ａｌｉｃｅ", "alice"), ("ali\u200bce", "alice"), ("alice", " "), ("alice", None)])
def test_two_person_r4_needs_two_different_people(by, second):
    # Red-team round 2: "alice" and "Alice" counted as two approvers.
    from opcp.gate import Approval
    gate = AuthorityGate(approver=lambda *a: Approval(True, by, second), two_person_r4=True)
    contract = CATALOGUE["send-customer-notification"]  # R4
    from opcp.envelope import Request
    r = gate.decide(contract, Request(contract.id, contract.version, "p", "s", "agent", {}, "confidential",
                                      idempotency_key="k"), "Ops")
    assert not r.allowed and "second, different approver" in r.reason


@pytest.mark.parametrize("by", ["", "   ", None, "\u200b", " \u2060 "])
def test_an_approval_must_name_its_approver(by):
    from opcp.envelope import Request
    from opcp.gate import Approval
    gate = AuthorityGate(approver=lambda *a: Approval(True, by))
    contract = CATALOGUE["post-journal-entry"]  # R2, no budget
    r = gate.decide(contract, Request(contract.id, contract.version, "p", "s", "agent", {}, "internal",
                                      idempotency_key="k"), "Controller")
    assert not r.allowed


def test_two_genuine_approvers_still_pass_and_are_recorded_trimmed():
    from opcp.envelope import Request
    from opcp.gate import Approval
    gate = AuthorityGate(approver=lambda *a: Approval(True, " alice ", "bob"), two_person_r4=True)
    contract = CATALOGUE["send-customer-notification"]
    r = gate.decide(contract, Request(contract.id, contract.version, "p", "s", "agent", {}, "confidential",
                                      idempotency_key="k"), "Ops")
    assert r.allowed and r.approved_by == ("alice", "bob")

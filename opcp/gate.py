"""Authority gate (spec section 10)."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Mapping

from .contract import Contract
from .envelope import Request
from .rclass import DEFAULT_POLICY, Decision, RClass


@dataclass(frozen=True)
class Approval:
    approved: bool
    by: str | None = None
    second_by: str | None = None
    reason: str = ""


Approver = Callable[[Request, Contract, RClass, Decision], Approval]


def same_person(a: str, b: str) -> bool:
    """Whether two approver identities name the same person, ignoring case, spacing and Unicode form.

    Identities come from a deployment's directory, so the gate cannot resolve aliases or look-alike
    characters from different scripts. It does refuse the cheap ways to count one person twice:
    "alice" and "Alice", or "alice" and "alice ".
    """
    return _canonical(a) == _canonical(b)


def _canonical(identity: str) -> str:
    # Invisible format characters (zero-width spaces and the like) are dropped, so they can't make a blank
    # name look filled in, or one person look like two.
    visible = "".join(ch for ch in unicodedata.normalize("NFKC", identity) if unicodedata.category(ch) != "Cf")
    return " ".join(visible.casefold().split())


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    rclass: RClass
    decision: Decision
    reason: str
    approved_by: tuple[str, ...] = ()
    notify: bool = False
    accountable_role: str | None = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "rclass": str(self.rclass),
            "decision": self.decision.value,
            "reason": self.reason,
            "approved_by": list(self.approved_by),
            "notify": self.notify,
            "accountable_role": self.accountable_role,
        }


@dataclass
class AuthorityGate:
    """Decides whether a call may proceed. Never consults a model."""

    policy: Mapping[RClass, Decision] = field(default_factory=lambda: dict(DEFAULT_POLICY))
    approver: Approver | None = None
    budgets: dict[str, int] = field(default_factory=dict)  # capability -> remaining pre-approved R2 calls
    overrides: Mapping[str, RClass] = field(default_factory=dict)  # capability -> raised class
    two_person_r4: bool = False

    def refund(self, result: GateResult, capability: str) -> None:
        """Return a budget unit when the call it authorised did not take effect."""
        if any(a.startswith("budget:") for a in result.approved_by):
            self.budgets[capability] = self.budgets.get(capability, 0) + 1

    def class_for(self, contract: Contract) -> RClass:
        override = self.overrides.get(contract.id)
        if override is None:
            return contract.rclass
        if override < contract.rclass:
            raise ValueError(f"override would lower {contract.id} from {contract.rclass} to {override}; overrides may only raise")
        return override

    def decide(self, contract: Contract, request: Request, accountable_role: str | None = None) -> GateResult:
        rclass = self.class_for(contract)
        decision = self.policy[rclass]

        def result(allowed: bool, reason: str, by: tuple[str, ...] = (), notify: bool = False) -> GateResult:
            return GateResult(allowed, rclass, decision, reason, by, notify, accountable_role)

        if decision is Decision.ALLOW:
            return result(True, "autonomous")
        if decision is Decision.ALLOW_AND_NOTIFY:
            return result(True, "autonomous, principal notified", notify=True)
        if decision is Decision.APPROVE_OR_BUDGET and self.budgets.get(contract.id, 0) > 0:
            self.budgets[contract.id] -= 1
            return result(True, f"within pre-approved budget ({self.budgets[contract.id]} left)", (f"budget:{contract.id}",))
        if self.approver is None:
            return result(False, f"{rclass} requires approval and no approver is configured")
        try:
            approval = self.approver(request, contract, rclass, decision)
        except Exception as exc:  # an approver failure is a refusal, never an approval
            return result(False, f"approver failed ({type(exc).__name__}); treated as declined")
        if not approval.approved:
            return result(False, approval.reason or "approval declined")
        if not _canonical(approval.by or ""):  # an approval must say who gave it
            return result(False, "approval names no approver; treated as declined")
        approvers: tuple[str, ...] = (approval.by.strip(),)
        if rclass is RClass.R4 and self.two_person_r4:
            second = (approval.second_by or "").strip()
            if not _canonical(second) or same_person(second, approval.by):
                return result(False, "R4 requires a second, different approver")
            approvers = (approval.by.strip(), second)
        return result(True, approval.reason or "approved", approvers)

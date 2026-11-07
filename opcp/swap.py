"""Supplier swap-drill primitives.

The evaluator is deliberately independent of supplier SDKs. It produces a
portable OPCP swap-drill evidence record that can be consumed by any control
plane implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import uuid4


@dataclass(frozen=True)
class SwapCase:
    case_id: str
    expected: str
    incumbent: str
    candidate: str
    incumbent_confidence: float | None = None
    candidate_confidence: float | None = None

    @property
    def passed(self) -> bool:
        return self.candidate == self.expected


@dataclass(frozen=True)
class SwapResult:
    capability: str
    incumbent: str
    candidate: str
    process_unchanged: bool
    context_lease_unchanged: bool
    authority_policy_unchanged: bool
    contract_conformance: bool
    regression_pass: bool
    material_exception_regression: bool
    cases: tuple[SwapCase, ...]
    started_at: str
    completed_at: str
    measured_seconds: float
    drill_id: str
    process_incumbent_revision: str
    process_candidate_revision: str
    context_lease_incumbent_revision: str
    context_lease_candidate_revision: str
    authority_policy_incumbent_revision: str
    authority_policy_candidate_revision: str
    execution_mode: str
    customer_visible: bool
    authority_effects_applied: bool
    contracting_days: float
    onboarding_days: float
    time_to_swap_confidence: str
    drill_date: str | None

    @property
    def passed(self) -> bool:
        return all(
            (
                self.process_unchanged,
                self.context_lease_unchanged,
                self.authority_policy_unchanged,
                self.contract_conformance,
                self.regression_pass,
                self.material_exception_regression,
            )
        )

    def evidence(self) -> dict[str, Any]:
        """Return a schema-compatible OPCP v0.3 swap-drill result."""
        return {
            "opcp_version": "0.3",
            "id": self.drill_id,
            "capability": self.capability,
            "incumbent_supplier": self.incumbent,
            "candidate_supplier": self.candidate,
            "execution": {
                "mode": self.execution_mode,
                "customer_visible": self.customer_visible,
                "authority_effects_applied": self.authority_effects_applied,
            },
            "invariants": {
                "process": {
                    "incumbent_revision": self.process_incumbent_revision,
                    "candidate_revision": self.process_candidate_revision,
                    "unchanged": self.process_unchanged,
                },
                "context_lease": {
                    "incumbent_revision": self.context_lease_incumbent_revision,
                    "candidate_revision": self.context_lease_candidate_revision,
                    "unchanged": self.context_lease_unchanged,
                },
                "authority_policy": {
                    "incumbent_revision": self.authority_policy_incumbent_revision,
                    "candidate_revision": self.authority_policy_candidate_revision,
                    "unchanged": self.authority_policy_unchanged,
                },
            },
            "promotion_gates": {
                "process_unchanged": self.process_unchanged,
                "context_lease_unchanged": self.context_lease_unchanged,
                "authority_policy_unchanged": self.authority_policy_unchanged,
                "contract_conformance": self.contract_conformance,
                "regression_pass": self.regression_pass,
                "material_exception_regression": self.material_exception_regression,
            },
            "regression": {
                "total_cases": len(self.cases),
                "passed_cases": sum(case.passed for case in self.cases),
                "failed_cases": sum(not case.passed for case in self.cases),
                "cases": [
                    {**asdict(case), "passed": case.passed}
                    for case in self.cases
                ],
            },
            "time_to_swap": {
                "contracting_days": self.contracting_days,
                "onboarding_days": self.onboarding_days,
                "technical_cutover_days": self.measured_seconds / 86400,
                "confidence": self.time_to_swap_confidence,
                **({"drill_date": self.drill_date} if self.drill_date else {}),
            },
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "decision": "passed" if self.passed else "failed",
        }


def evaluate_swap(
    *,
    capability: str,
    incumbent: str,
    candidate: str,
    cases: Sequence[SwapCase],
    process_unchanged: bool = True,
    context_lease_unchanged: bool = True,
    authority_policy_unchanged: bool = True,
    contract_conformance: bool = True,
    started_at: str | None = None,
    completed_at: str | None = None,
    measured_seconds: float = 0.0,
    drill_id: str | None = None,
    process_incumbent_revision: str = "process:current",
    process_candidate_revision: str = "process:current",
    context_lease_incumbent_revision: str = "context-lease:current",
    context_lease_candidate_revision: str = "context-lease:current",
    authority_policy_incumbent_revision: str = "authority-policy:current",
    authority_policy_candidate_revision: str = "authority-policy:current",
    execution_mode: str = "shadow",
    customer_visible: bool = False,
    authority_effects_applied: bool = False,
    contracting_days: float = 0.0,
    onboarding_days: float = 0.0,
    time_to_swap_confidence: str = "estimated",
    drill_date: str | None = None,
) -> SwapResult:
    """Evaluate a candidate supplier against the incumbent.

    The candidate is promotable only when every normative gate passes. Business
    regression is intentionally separate from structural contract conformance.
    Revision equality is authoritative for the three ownership invariants; a
    caller cannot accidentally assert portability while supplying different
    process, context-lease or authority-policy revisions.
    """
    if measured_seconds < 0 or contracting_days < 0 or onboarding_days < 0:
        raise ValueError("swap timing values cannot be negative")
    if time_to_swap_confidence not in {"estimated", "proven"}:
        raise ValueError("time_to_swap_confidence must be 'estimated' or 'proven'")
    if time_to_swap_confidence == "proven" and not drill_date:
        drill_date = date.today().isoformat()
    if drill_date:
        date.fromisoformat(drill_date)
    if execution_mode not in {"shadow", "rehearsal", "production"}:
        raise ValueError("execution_mode must be shadow, rehearsal, or production")

    process_unchanged = process_unchanged and (
        process_incumbent_revision == process_candidate_revision
    )
    context_lease_unchanged = context_lease_unchanged and (
        context_lease_incumbent_revision == context_lease_candidate_revision
    )
    authority_policy_unchanged = authority_policy_unchanged and (
        authority_policy_incumbent_revision == authority_policy_candidate_revision
    )

    regression_pass = all(case.passed for case in cases)
    material_exception_regression = all(
        not (case.expected in {"fail", "refer"} and case.candidate != case.expected)
        for case in cases
    )
    now = datetime.now(timezone.utc).isoformat()
    return SwapResult(
        capability=capability,
        incumbent=incumbent,
        candidate=candidate,
        process_unchanged=process_unchanged,
        context_lease_unchanged=context_lease_unchanged,
        authority_policy_unchanged=authority_policy_unchanged,
        contract_conformance=contract_conformance,
        regression_pass=regression_pass,
        material_exception_regression=material_exception_regression,
        cases=tuple(cases),
        started_at=started_at or now,
        completed_at=completed_at or now,
        measured_seconds=measured_seconds,
        drill_id=drill_id or f"swap-{uuid4().hex}",
        process_incumbent_revision=process_incumbent_revision,
        process_candidate_revision=process_candidate_revision,
        context_lease_incumbent_revision=context_lease_incumbent_revision,
        context_lease_candidate_revision=context_lease_candidate_revision,
        authority_policy_incumbent_revision=authority_policy_incumbent_revision,
        authority_policy_candidate_revision=authority_policy_candidate_revision,
        execution_mode=execution_mode,
        customer_visible=customer_visible,
        authority_effects_applied=authority_effects_applied,
        contracting_days=contracting_days,
        onboarding_days=onboarding_days,
        time_to_swap_confidence=time_to_swap_confidence,
        drill_date=drill_date,
    )


def validate_swap_result(result: Mapping[str, Any]) -> list[str]:
    """Perform protocol-level invariants independent of JSON Schema."""
    errors: list[str] = []
    gates = result.get("promotion_gates", {})
    gate_names = (
        "process_unchanged",
        "context_lease_unchanged",
        "authority_policy_unchanged",
        "contract_conformance",
        "regression_pass",
        "material_exception_regression",
    )
    expected = "passed" if all(gates.get(name) is True for name in gate_names) else "failed"
    if result.get("decision") != expected:
        errors.append(f"decision must be {expected!r} for the supplied promotion gates")
    execution = result.get("execution", {})
    if execution.get("mode") == "shadow" and execution.get("customer_visible"):
        errors.append("shadow drills cannot be customer-visible")
    if execution.get("mode") == "shadow" and execution.get("authority_effects_applied"):
        errors.append("shadow drills cannot apply authority effects")
    return errors

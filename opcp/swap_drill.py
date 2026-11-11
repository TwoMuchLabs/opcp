"""Executable swap-drill evidence runner.

This module turns a portable OPCP v0.3 swap-drill evidence file into a
machine-checkable result suitable for a control-plane integration. It does not
invoke supplier SDKs or mutate production state; it validates the evidence,
recomputes the regression outcome, and applies protocol safety gates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ._io import errors as schema_errors
from ._io import schema_validator
from .swap import validate_swap_result


REQUIRED_TOP_LEVEL = {
    "opcp_version",
    "id",
    "capability",
    "incumbent_supplier",
    "candidate_supplier",
    "execution",
    "invariants",
    "promotion_gates",
    "regression",
    "time_to_swap",
    "started_at",
    "completed_at",
    "decision",
}

REQUIRED_GATES = (
    "process_unchanged",
    "context_lease_unchanged",
    "authority_policy_unchanged",
    "contract_conformance",
    "regression_pass",
    "material_exception_regression",
)


def load_swap_evidence(path: str | Path) -> dict[str, Any]:
    """Load one JSON-encoded OPCP swap-drill evidence record."""
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("swap-drill evidence must be a JSON object")
    return payload


def evaluate_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and summarize a swap-drill evidence record.

    The runner intentionally recomputes regression and gate decisions instead
    of trusting summary booleans supplied by an upstream control plane.
    """
    errors: list[str] = []
    # SWAP-DRILL section 1: the record must validate against the schema. Checked here so
    # that, for example, a "proven" time-to-swap without a drill date is rejected (section 8).
    errors.extend(f"schema: {problem}" for problem in schema_errors(schema_validator("swap-drill"), evidence))
    missing = sorted(REQUIRED_TOP_LEVEL - set(evidence))
    if missing:
        errors.extend(f"missing top-level field: {field}" for field in missing)

    if evidence.get("opcp_version") != "0.3":
        errors.append("swap-drill runner requires OPCP v0.3 evidence")

    regression = evidence.get("regression", {})
    cases = regression.get("cases", []) if isinstance(regression, Mapping) else []
    if not isinstance(cases, list):
        errors.append("regression.cases must be a list")
        cases = []

    recomputed_pass = all(
        isinstance(case, Mapping) and case.get("candidate") == case.get("expected")
        for case in cases
    )
    recomputed_exception_pass = all(
        isinstance(case, Mapping)
        and not (
            case.get("expected") in {"fail", "refer"}
            and case.get("candidate") != case.get("expected")
        )
        for case in cases
    )

    gates = evidence.get("promotion_gates", {})
    if not isinstance(gates, Mapping):
        gates = {}
        errors.append("promotion_gates must be an object")

    if gates.get("regression_pass") is not recomputed_pass:
        errors.append("regression_pass does not match regression cases")
    if gates.get("material_exception_regression") is not recomputed_exception_pass:
        errors.append("material_exception_regression does not match regression cases")

    errors.extend(validate_swap_result(evidence))

    blocking_reasons = [
        f"promotion gate failed: {name}"
        for name in REQUIRED_GATES
        if gates.get(name) is not True
    ]

    passed = not errors and not blocking_reasons
    return {
        "id": evidence.get("id"),
        "capability": evidence.get("capability"),
        "incumbent_supplier": evidence.get("incumbent_supplier"),
        "candidate_supplier": evidence.get("candidate_supplier"),
        "decision": "passed" if passed else "failed",
        "regression": {
            "total_cases": len(cases),
            "passed_cases": sum(
                isinstance(case, Mapping) and case.get("candidate") == case.get("expected")
                for case in cases
            ),
        },
        "promotion_ready": passed,
        "blocking_reasons": blocking_reasons,
        "errors": errors,
    }


def run_swap_drill(path: str | Path) -> dict[str, Any]:
    """Load and evaluate a swap-drill evidence file."""
    return evaluate_evidence(load_swap_evidence(path))

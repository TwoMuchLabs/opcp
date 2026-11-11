from pathlib import Path

from opcp.swap_drill import evaluate_evidence, run_swap_drill


FIXTURE = Path(__file__).parents[1] / "examples" / "sme-credit-swap-drill.json"


def test_sme_swap_fixture_is_promotion_ready():
    result = run_swap_drill(FIXTURE)
    assert result["decision"] == "passed"
    assert result["promotion_ready"] is True
    assert result["regression"] == {"total_cases": 4, "passed_cases": 4}
    assert result["errors"] == []


def test_runner_recomputes_regression_gate():
    evidence = {
        "opcp_version": "0.3",
        "id": "swap-test",
        "capability": "extract-application-documents",
        "incumbent_supplier": "supplier-a",
        "candidate_supplier": "supplier-b",
        "execution": {
            "mode": "shadow",
            "customer_visible": False,
            "authority_effects_applied": False,
        },
        "invariants": {},
        "promotion_gates": {
            "process_unchanged": True,
            "context_lease_unchanged": True,
            "authority_policy_unchanged": True,
            "contract_conformance": True,
            "regression_pass": True,
            "material_exception_regression": True,
        },
        "regression": {
            "cases": [{"case_id": "bad-case", "expected": "pass", "candidate": "fail"}]
        },
        "time_to_swap": {},
        "started_at": "2026-10-30T00:00:00+00:00",
        "completed_at": "2026-10-30T00:00:01+00:00",
        "decision": "passed",
    }
    result = evaluate_evidence(evidence)
    assert result["decision"] == "failed"
    assert result["promotion_ready"] is False
    assert "regression_pass does not match regression cases" in result["errors"]


def test_runner_blocks_customer_visible_shadow():
    evidence = __import__("json").loads(FIXTURE.read_text())
    evidence["execution"]["customer_visible"] = True
    result = evaluate_evidence(evidence)
    assert result["decision"] == "failed"
    assert "shadow drills cannot be customer-visible" in result["errors"]

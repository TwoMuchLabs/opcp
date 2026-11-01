import json
from pathlib import Path

from opcp.evidence_service import evaluate_swap_evidence, evaluate_swap_evidence_file


FIXTURE = Path(__file__).parents[1] / "examples" / "sme-credit-swap-drill.json"
BLOCKED_FIXTURE = Path(__file__).parents[1] / "examples" / "kyc-document-review-blocked-swap-drill.json"


def test_runtime_boundary_evaluates_in_memory_fixture():
    evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = evaluate_swap_evidence(evidence)

    assert result["promotion_ready"] is True
    assert result["decision"] == "passed"


def test_runtime_boundary_matches_file_evaluator():
    evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert evaluate_swap_evidence(evidence) == evaluate_swap_evidence_file(FIXTURE)


def test_runtime_boundary_blocks_failed_kyc_swap():
    evidence = json.loads(BLOCKED_FIXTURE.read_text(encoding="utf-8"))
    result = evaluate_swap_evidence(evidence)

    assert result["promotion_ready"] is False
    assert result["decision"] == "failed"
    assert result["regression"]["total_cases"] == 6
    assert result["regression"]["passed_cases"] == 4
    assert result["errors"]


def test_runtime_boundary_matches_blocked_file_evaluator():
    evidence = json.loads(BLOCKED_FIXTURE.read_text(encoding="utf-8"))
    assert evaluate_swap_evidence(evidence) == evaluate_swap_evidence_file(BLOCKED_FIXTURE)

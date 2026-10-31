from pathlib import Path

from opcp.evidence_service import evaluate_swap_evidence, evaluate_swap_evidence_file


FIXTURE = Path(__file__).parents[1] / "examples" / "sme-credit-swap-drill.json"


def test_runtime_boundary_evaluates_in_memory_fixture():
    import json

    evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = evaluate_swap_evidence(evidence)

    assert result["promotion_ready"] is True
    assert result["decision"] == "passed"


def test_runtime_boundary_matches_file_evaluator():
    import json

    evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert evaluate_swap_evidence(evidence) == evaluate_swap_evidence_file(FIXTURE)

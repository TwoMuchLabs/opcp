import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from opcp.swap import SwapCase, evaluate_swap, validate_swap_result


SCHEMA = json.loads((Path(__file__).parents[1] / "schema" / "swap-drill.schema.json").read_text())


def validate(result):
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    return sorted(validator.iter_errors(result), key=lambda error: list(error.path))


def test_swap_result_is_v03_schema_compatible():
    result = evaluate_swap(
        capability="verify-identity",
        incumbent="supplier-a",
        candidate="supplier-b",
        cases=[
            SwapCase("clean", "pass", "pass", "pass"),
            SwapCase("sanctions", "fail", "fail", "fail"),
        ],
        measured_seconds=7200,
    )

    evidence = result.evidence()
    assert not validate(evidence)
    assert evidence["opcp_version"] == "0.3"
    assert evidence["decision"] == "passed"
    assert validate_swap_result(evidence) == []


def test_process_revision_change_blocks_promotion():
    result = evaluate_swap(
        capability="verify-identity",
        incumbent="supplier-a",
        candidate="supplier-b",
        cases=[SwapCase("clean", "pass", "pass", "pass")],
        process_incumbent_revision="process:17",
        process_candidate_revision="process:18",
    )

    assert not result.passed
    evidence = result.evidence()
    assert evidence["decision"] == "failed"
    assert evidence["promotion_gates"]["process_unchanged"] is False
    assert not validate(evidence)


def test_context_lease_revision_change_blocks_promotion():
    result = evaluate_swap(
        capability="verify-identity",
        incumbent="supplier-a",
        candidate="supplier-b",
        cases=[SwapCase("clean", "pass", "pass", "pass")],
        context_lease_incumbent_revision="context-lease:17",
        context_lease_candidate_revision="context-lease:18",
    )

    assert not result.passed
    evidence = result.evidence()
    assert evidence["promotion_gates"]["context_lease_unchanged"] is False


def test_authority_policy_revision_change_blocks_promotion():
    result = evaluate_swap(
        capability="verify-identity",
        incumbent="supplier-a",
        candidate="supplier-b",
        cases=[SwapCase("clean", "pass", "pass", "pass")],
        authority_policy_incumbent_revision="authority-policy:17",
        authority_policy_candidate_revision="authority-policy:18",
    )

    assert not result.passed
    evidence = result.evidence()
    assert evidence["promotion_gates"]["authority_policy_unchanged"] is False


def test_shadow_drill_cannot_apply_authority_effects():
    result = evaluate_swap(
        capability="post-ledger-entry",
        incumbent="supplier-a",
        candidate="supplier-b",
        cases=[SwapCase("clean", "pass", "pass", "pass")],
        authority_effects_applied=True,
    )

    evidence = result.evidence()
    assert validate_swap_result(evidence) == [
        "shadow drills cannot apply authority effects"
    ]


def test_proven_time_to_swap_requires_drill_date():
    result = evaluate_swap(
        capability="verify-identity",
        incumbent="supplier-a",
        candidate="supplier-b",
        cases=[SwapCase("clean", "pass", "pass", "pass")],
        time_to_swap_confidence="proven",
        drill_date="2026-10-30",
    )

    evidence = result.evidence()
    assert not validate(evidence)
    assert evidence["time_to_swap"]["confidence"] == "proven"
    assert evidence["time_to_swap"]["drill_date"] == "2026-10-30"


def test_proven_time_to_swap_without_date_is_rejected_by_schema_only_when_record_is_missing():
    result = evaluate_swap(
        capability="verify-identity",
        incumbent="supplier-a",
        candidate="supplier-b",
        cases=[SwapCase("clean", "pass", "pass", "pass")],
        time_to_swap_confidence="estimated",
    )
    evidence = result.evidence()
    evidence["time_to_swap"]["confidence"] = "proven"
    evidence["time_to_swap"].pop("drill_date", None)

    assert validate(evidence)

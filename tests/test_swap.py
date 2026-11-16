from opcp.swap import SwapCase, evaluate_swap


def test_successful_swap_requires_all_invariants_and_regression():
    cases = [
        SwapCase("clean", "pass", "pass", "pass"),
        SwapCase("mismatch", "refer", "refer", "refer"),
        SwapCase("sanctions", "fail", "fail", "fail"),
    ]
    result = evaluate_swap(
        capability="extract-application-documents",
        incumbent="supplier-a",
        candidate="supplier-b",
        cases=cases,
        measured_seconds=7200,
    )

    assert result.passed
    assert result.evidence()["decision"] == "passed"
    assert result.evidence()["time_to_swap"]["technical_cutover_days"] == 2 / 24


def test_candidate_regression_blocks_promotion():
    cases = [
        SwapCase("clean", "pass", "pass", "pass"),
        SwapCase("sanctions", "fail", "fail", "pass"),
    ]
    result = evaluate_swap(
        capability="verify-identity",
        incumbent="supplier-a",
        candidate="supplier-b",
        cases=cases,
    )

    assert not result.passed
    assert not result.regression_pass
    assert not result.material_exception_regression


def test_context_or_authority_change_blocks_promotion_even_when_outputs_match():
    cases = [SwapCase("clean", "pass", "pass", "pass")]
    result = evaluate_swap(
        capability="verify-business",
        incumbent="supplier-a",
        candidate="supplier-b",
        cases=cases,
        context_lease_unchanged=False,
    )

    assert not result.passed

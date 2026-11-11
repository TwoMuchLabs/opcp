"""Run the language-neutral conformance fixtures in conformance/ against the reference implementation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opcp.swap_drill import evaluate_evidence

ROOT = Path(__file__).resolve().parent.parent
SWAP_DRILL = sorted((ROOT / "conformance" / "swap-drill").glob("*.json"))


def outcome(result: dict) -> str:
    """Map the reference evaluator's result onto the fixture outcomes in conformance/README.md."""
    if result["errors"]:
        return "reject"
    return "pass" if result["promotion_ready"] else "fail"


def test_swap_drill_suite_is_present():
    assert len(SWAP_DRILL) >= 15


@pytest.mark.parametrize("path", SWAP_DRILL, ids=lambda p: p.stem)
def test_swap_drill_fixture(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert fixture["guarantee"], "every fixture states the guarantee it checks"
    assert fixture["expected_outcome"] in {"pass", "fail", "reject"}
    result = evaluate_evidence(fixture["evidence"])
    assert outcome(result) == fixture["expected_outcome"], (fixture["guarantee"], result["errors"])

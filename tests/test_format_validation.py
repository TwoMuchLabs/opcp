"""JSON Schema formats are asserted the same way on every machine (opcp._io.ENFORCED_FORMATS).

Before, `date` was checked everywhere but `date-time` and `uri` only where optional packages happened
to be installed, so one document could pass on one machine and fail on another.
"""

import json
from pathlib import Path

import pytest

from opcp._io import ENFORCED_FORMATS, FORMAT_CHECKER, errors, schema_validator, validator_for

ROOT = Path(__file__).resolve().parent.parent

CASES = {
    "date": ("2026-10-31", "2026-13-45"),
    "date-time": ("2026-10-31T09:30:00+08:00", "yesterday afternoon"),
    "time": ("09:30:00Z", "half past nine"),
    "uri": ("https://github.com/TwoMuchLabs/opcp", "not a uri at all"),
    "uri-reference": ("../schema/route.schema.json", "\\\\bad\\ref"),
    "email": ("hello@twomuchlabs.com", "not-an-email"),
    "ipv4": ("192.0.2.1", "999.0.0.1"),
    "ipv6": ("2001:db8::1", "2001:db8:::1"),
    "uuid": ("123e4567-e89b-12d3-a456-426614174000", "not-a-uuid"),
    "regex": ("^[A-Z]{3}$", "([unclosed"),
}


def test_every_enforced_format_has_a_case():
    assert set(CASES) == set(ENFORCED_FORMATS)


@pytest.mark.parametrize("fmt", sorted(CASES))
def test_enforced_formats_reject_bad_values(fmt):
    good, bad = CASES[fmt]
    v = validator_for({"type": "string", "format": fmt})
    assert not errors(v, good), (fmt, good)
    assert errors(v, bad), (fmt, bad)


def test_other_formats_are_annotations_everywhere():
    """A format outside the list is never asserted, whatever happens to be installed."""
    assert "hostname" not in FORMAT_CHECKER.checkers
    assert not errors(validator_for({"type": "string", "format": "hostname"}), "not a host!")


def test_swap_drill_timestamps_are_checked():
    """SWAP-DRILL records carry date-time fields; a free-text timestamp is a schema error."""
    record = json.loads((ROOT / "examples" / "sme-credit-swap-drill.json").read_text(encoding="utf-8"))
    assert not errors(schema_validator("swap-drill"), record)
    record["started_at"] = "yesterday afternoon"
    assert any("started_at" in e for e in errors(schema_validator("swap-drill"), record))


def test_contract_output_date_time_is_checked():
    """A human_task output's completed_at must be a real timestamp (catalogue/review-identity-exception.yaml)."""
    from opcp.contract import load_catalogue
    from opcp._paths import data_dir

    contract = load_catalogue(data_dir("catalogue"))["review-identity-exception"]
    output = {"outcome": "pass", "assignee_role": "Reviewer", "completed_at": "sometime"}
    assert any("completed_at" in e for e in contract.output_errors(output))

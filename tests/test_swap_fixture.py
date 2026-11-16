import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


def test_sme_credit_swap_fixture_validates():
    root = Path(__file__).parents[1]
    schema = json.loads((root / "schema" / "swap-drill.schema.json").read_text())
    fixture = json.loads((root / "examples" / "sme-credit-swap-drill.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert list(validator.iter_errors(fixture)) == []

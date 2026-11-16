from pathlib import Path

from opcp.cli import main


FIXTURE = Path(__file__).parents[1] / "examples" / "sme-credit-swap-drill.json"


def test_swap_drill_cli_accepts_promotion_ready_fixture(capsys):
    assert main(["swap-drill", str(FIXTURE)]) == 0
    output = capsys.readouterr().out
    assert '"promotion_ready": true' in output
    assert '"decision": "passed"' in output


def test_swap_drill_cli_returns_failure_for_invalid_evidence(tmp_path, capsys):
    evidence = tmp_path / "invalid.json"
    evidence.write_text('{"opcp_version":"0.2"}', encoding="utf-8")
    assert main(["swap-drill", str(evidence)]) == 1
    output = capsys.readouterr().out
    assert '"promotion_ready": false' in output
    assert "swap-drill runner requires OPCP v0.3 evidence" in output

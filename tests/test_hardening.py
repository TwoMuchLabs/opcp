"""Generated pages and document loading (red-team R2-08, R2-09)."""

import pytest

from opcp._io import ValidationFailed
from opcp.scorecard import evaluate

def test_generated_reports_forbid_scripts_and_network_requests(tmp_path):
    # Red-team round 2: nothing in the report or readout should be able to run a script or reach the network.
    from opcp.readout import render_html as readout_html
    from opcp.scorecard import render_html as report_html
    from opcp._io import load_document
    from opcp._paths import data_dir
    doc = load_document(data_dir("examples") / "example-bank.yaml")
    for html in (report_html(evaluate(doc)), readout_html(doc)):
        head = html.split("</head>", 1)[0]
        assert "Content-Security-Policy" in head and "default-src 'none'" in head and "script-src" not in head
        assert "<script" not in html


def test_yaml_alias_bombs_are_refused(tmp_path):
    from opcp._io import load_document
    lines = ['a: &a ["x","x","x","x","x","x","x","x","x","x"]']
    for prev, name in zip("abcdef", "bcdefg"):
        lines.append(f"{name}: &{name} [" + ",".join([f"*{prev}"] * 10) + "]")
    bomb = tmp_path / "bomb.yaml"
    bomb.write_text("\n".join(lines) + "\n")  # 10 million values once expanded
    with pytest.raises(ValidationFailed, match="YAML aliases"):
        load_document(bomb)
    small = tmp_path / "small.yaml"
    small.write_text("base: &b {region: SG}\nfirst: *b\nsecond: *b\n")
    assert load_document(small) == {"base": {"region": "SG"}, "first": {"region": "SG"}, "second": {"region": "SG"}}
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    assert load_document(empty) is None

import copy
import json
import socket

import pytest

from opcp._io import ValidationFailed, load_document
from opcp._paths import data_dir
from opcp.cli import main
from opcp.conformance import check_adapter
from opcp.demo import build
from opcp.scorecard import LOCKED, PARTIAL, READY, evaluate, render_html, template

EXAMPLE = load_document(data_dir("examples") / "example-bank.yaml")


def proc(**changes):
    doc = copy.deepcopy(EXAMPLE)
    p = doc["processes"][3]  # the Ready example: customer notifications
    p.update(changes)
    doc["processes"] = [p]
    return doc


def test_example_ratings():
    result = evaluate(EXAMPLE)
    ratings = {p.id: p.rating for p in result.processes}
    assert ratings == {"onboarding-idv": LOCKED, "payments-sanctions": PARTIAL, "loan-docs": LOCKED,
                       "customer-notifications": READY, "supplier-invoices": LOCKED}


def test_paper_example_time_to_swap_is_120_days():
    idv = next(p for p in evaluate(EXAMPLE).processes if p.id == "onboarding-idv")
    assert idv.swap["total_days"] == 120


def test_weakest_link_rule():
    r = evaluate(proc(authority="none"))
    assert r.processes[0].rating == LOCKED  # every other measure is Ready


@pytest.mark.parametrize("swap,expected", [((30, 30, 30), READY), ((60, 60, 60), PARTIAL), ((100, 50, 31), LOCKED)])
def test_time_to_swap_thresholds(swap, expected):
    c, o, cut = swap
    r = evaluate(proc(time_to_swap={"contracting_days": c, "onboarding_days": o, "cutover_days": cut, "confidence": "estimated"}))
    assert next(m for m in r.processes[0].measures if m.key == "swap").rating == expected


def test_contract_terms():
    locked = evaluate(proc(contract={"data_return": False, "termination_assistance": True, "notice_days": 30}))
    partial = evaluate(proc(contract={"data_return": True, "termination_assistance": False, "notice_days": 30}))
    get = lambda r: next(m for m in r.processes[0].measures if m.key == "contract").rating
    assert get(locked) == LOCKED and get(partial) == PARTIAL


def test_concentration_flag():
    result = evaluate(EXAMPLE)
    top = result.concentration[0]
    assert top.supplier == "Vendor A (fictional)" and top.share == 0.75 and top.over_limit


def test_invalid_assessment_reports_field_paths():
    doc = copy.deepcopy(EXAMPLE)
    doc["processes"][0]["authority"] = "maybe"
    with pytest.raises(ValidationFailed) as exc:
        evaluate(doc)
    assert any("processes/0/authority" in p for p in exc.value.problems)


def test_duplicate_process_ids_rejected():
    doc = copy.deepcopy(EXAMPLE)
    doc["processes"].append(doc["processes"][0])
    with pytest.raises(ValidationFailed):
        evaluate(doc)


def test_template_is_a_valid_assessment(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text(template())
    from opcp.scorecard import evaluate_file
    assert evaluate_file(path).processes


def test_html_escapes_user_text():
    doc = proc(name="<script>alert(1)</script>")
    html = render_html(evaluate(doc))
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_cli_run_offline(tmp_path, monkeypatch, capsys):
    def no_network(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", no_network)
    src = tmp_path / "example.yaml"
    assert main(["scorecard", "example", str(src)]) == 0
    out, js = tmp_path / "r.html", tmp_path / "r.json"
    assert main(["scorecard", "run", str(src), "-o", str(out), "--json", str(js)]) == 0
    assert "No data left this machine" in out.read_text()
    assert json.loads(js.read_text())["summary"]["critical_processes"] == 4


def test_cli_init_refuses_to_overwrite(tmp_path):
    path = tmp_path / "a.yaml"
    assert main(["scorecard", "init", str(path)]) == 0
    assert main(["scorecard", "init", str(path)]) == 1


def test_cli_validate_contracts():
    paths = [str(p) for p in sorted((data_dir("catalogue")).glob("*.yaml"))]
    assert main(["validate", "contract", *paths]) == 0


def test_all_demo_adapters_pass_conformance():
    plane = build()
    for adapter in plane.adapters.values():
        report = check_adapter(adapter, plane.contracts[adapter.profile.capability])
        assert report.passed, report.render()


def test_proven_time_to_swap_needs_a_drill_dated_by_the_assessment():
    # Red-team round 2: a drill dated after the assessment (not yet run) still counted as proven.
    import copy

    from opcp._io import ValidationFailed, load_document
    from opcp._paths import data_dir
    from opcp.scorecard import evaluate, evaluate_answers

    doc = copy.deepcopy(load_document(data_dir("examples") / "example-bank.yaml"))
    proven = [p for p in doc["processes"] if p["time_to_swap"].get("confidence") == "proven"]
    assert proven, "the example needs a proven process for this test"
    proven[0]["time_to_swap"]["drill_date"] = "2031-01-01"
    with pytest.raises(ValidationFailed, match="after the assessment date"):
        evaluate(doc)
    proven[0]["time_to_swap"]["drill_date"] = doc["assessment_date"]  # a drill on the day still counts
    evaluate(doc)

    answers = copy.deepcopy(load_document(data_dir("examples") / "example-bank-answers.yaml"))
    target = next(p for p in answers["processes"] if "ERS-EXT-04" in p["answers"])
    target["answers"]["ERS-EXT-04"]["value"] = "2031-01-01"
    with pytest.raises(ValidationFailed, match="after the assessment date"):
        evaluate_answers(answers)

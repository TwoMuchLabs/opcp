"""The sponsor readout pack."""

import copy
import datetime as dt

from opcp._io import load_document
from opcp._paths import data_dir
from opcp.cli import main
from opcp.readout import decisions, render_html, renewals
from opcp.registers import _assessment
from opcp.scorecard import evaluate_answers

ANSWERS = load_document(data_dir("examples") / "example-bank-answers.yaml")
TODAY = dt.date(2026, 10, 24)


def setup(doc=None):
    doc = copy.deepcopy(doc or ANSWERS)
    return doc, _assessment(doc), evaluate_answers(doc)


def test_renewals_compute_the_last_day_to_give_notice():
    _, assessment, result = setup()
    (r,) = renewals(assessment, result, TODAY)  # only onboarding has an end date in the example
    assert r["end"] == dt.date(2027, 6, 30) and r["notice_days"] == 180
    assert r["notice_by"] == dt.date(2027, 1, 1)
    assert "termination assistance" in r["gaps"]


def test_renewals_outside_18_months_are_left_out():
    doc = copy.deepcopy(ANSWERS)
    doc["processes"][0]["answers"]["ERS-CON-05"]["value"] = "2030-01-01"
    _, assessment, result = setup(doc)
    assert renewals(assessment, result, TODAY) == []


def test_decisions_are_ordered_and_specific():
    _, assessment, result = setup()
    decs = decisions(assessment, result, TODAY)
    whats = [d["what"] for d in decs]
    assert whats[0].startswith("Use the Vendor A (fictional) renewal")
    assert "2027-01-01" in decs[0]["why"]
    assert any("second supplier" in w and "Vendor A" in w for w in whats)  # 67% over the 50% limit
    assert any("Bring the rules of Customer onboarding" in w for w in whats)
    assert any(w.startswith("Rehearse a swap for 2 processes") for w in whats)


def test_a_passed_notice_date_is_called_out():
    _, assessment, result = setup()
    late = decisions(assessment, result, dt.date(2027, 2, 1))
    assert "has passed" in late[0]["why"]


def test_html_has_the_grid_tiles_and_status():
    doc, _, _ = setup()
    page = render_html(doc, today=TODAY)
    assert "Where each process stands" in page and "Decisions for the sponsor" in page
    assert "1 of 3" in page                      # one proven time-to-swap
    assert "Not a certification" in page and "Reviewed by R. Reviewer" in page
    assert page.count("<tr>") >= 4               # header + three processes in the grid
    assert "<script" not in page                 # a static, printable page


def test_assessment_files_work_too():
    page = render_html(load_document(data_dir("examples") / "example-bank.yaml"), today=TODAY)
    assert "Where each process stands" in page


def test_cli_readout(tmp_path, capsys):
    out = tmp_path / "readout.html"
    src = str(data_dir("examples") / "example-bank-answers.yaml")
    assert main(["scorecard", "readout", src, "-o", str(out)]) == 0
    assert out.read_text().startswith("<!doctype html>")
    assert main(["scorecard", "readout", src, "-o", str(out)]) == 1
    assert main(["scorecard", "readout", src, "-o", str(out), "--force"]) == 0

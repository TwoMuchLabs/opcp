"""Opt-in tamper evidence for the event log (issue #33): each entry carries the hash of the one before."""

import json

import pytest

from opcp.cli import main
from opcp.eventlog import GENESIS, EventLog, line_hash, verify_chain, verify_file


def chained(n=5, tmp_path=None):
    log = EventLog(tmp_path / "live.jsonl" if tmp_path else None, chain=True)
    for i in range(n):
        log.append("gate", f"t{i}", allowed=i % 2 == 0, rclass="R2")
    return log


def lines(log):
    return [json.dumps(e, sort_keys=True, default=str) for e in log]


def test_unchained_log_is_unchanged_by_default():
    log = EventLog()
    log.append("gate", "t", allowed=True)
    assert "prev_hash" not in log.entries()[0]


def test_chain_links_every_entry():
    log = chained()
    entries = log.entries()
    assert entries[0]["prev_hash"] == GENESIS
    for previous, entry in zip(lines(log), entries[1:]):
        assert entry["prev_hash"] == line_hash(previous)
    assert verify_chain(lines(log), log.head()).ok


@pytest.mark.parametrize("tamper, line", [
    (lambda ls: ls.__setitem__(2, ls[2].replace('"allowed": true', '"allowed": false')), 4),  # edit an entry
    (lambda ls: ls.insert(2, ls[1]), 3),                                                      # insert a copy
    (lambda ls: ls.pop(1), 2),                                                                # delete an entry
    (lambda ls: ls.__setitem__(slice(1, 3), [ls[2], ls[1]]), 2),                              # reorder
])
def test_tampering_is_detected_where_it_happens(tamper, line):
    exported = lines(chained())
    tamper(exported)
    result = verify_chain(exported)
    assert not result.ok and result.line == line, result


def test_truncation_needs_the_head_kept_elsewhere():
    log = chained()
    truncated = lines(log)[:-1]
    assert verify_chain(truncated).ok                       # undetectable from the file alone
    result = verify_chain(truncated, expected_head=log.head())
    assert not result.ok and "missing from the end" in result.problem


def test_file_written_live_and_exported_verify(tmp_path):
    log = chained(tmp_path=tmp_path)
    exported = log.export_jsonl(tmp_path / "export.jsonl")
    assert verify_file(exported, log.head()).ok
    assert verify_file(tmp_path / "live.jsonl", log.head()).ok
    assert exported.read_text() == (tmp_path / "live.jsonl").read_text()


def test_unchained_or_malformed_logs_are_reported(tmp_path):
    plain = EventLog()
    plain.append("gate", "t")
    assert "not chained" in verify_chain(lines(plain)).problem
    assert verify_chain(["{not json"]).problem == "not a JSON entry"


def test_cli_verify(tmp_path, capsys):
    log = chained(tmp_path=tmp_path)
    path = tmp_path / "live.jsonl"
    assert main(["log", "verify", str(path), "--head", log.head()]) == 0
    text = path.read_text().splitlines()
    text[0] = text[0].replace('"t0"', '"tX"')
    path.write_text("\n".join(text) + "\n")
    assert main(["log", "verify", str(path)]) == 1
    assert "line 2" in capsys.readouterr().err


def test_runtime_with_a_chained_log_verifies():
    import sys
    sys.path.insert(0, "tests")
    from test_runtime import CALL, CATALOGUE, PERSON, TODAY, Fixed, profile, route
    from opcp.runtime import ControlPlane

    p = ControlPlane(CATALOGUE, [Fixed(profile("a"))], [route(["a"])], log=EventLog(chain=True), today=TODAY)
    p.call("verify-identity", PERSON, idempotency_key="k", **CALL)
    p.call("unknown", {}, idempotency_key="k2", **CALL)
    assert verify_chain(lines(p.log), p.log.head()).ok and len(p.log) > 4

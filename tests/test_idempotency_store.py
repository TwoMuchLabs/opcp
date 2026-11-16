"""Idempotency records that survive a restart or a crash (issue #31, reference runtime only)."""

from __future__ import annotations

import datetime as dt
import json
import os
import stat

import pytest

from opcp.adapter import Adapter, AdapterResult, DefiniteFailure
from opcp.gate import AuthorityGate
from opcp.idempotency import FileIdempotencyStore, IdempotencyStore
from opcp.rclass import RClass
from opcp.router import Route
from opcp.runtime import ControlPlane

from test_runtime import CALL, CATALOGUE, PERSON, TODAY, profile

JOURNAL = {"entry_date": "2026-10-31", "currency": "SGD",
           "lines": [{"account": "1", "debit": 1, "credit": 0}, {"account": "2", "debit": 0, "credit": 1}]}
JCALL = dict(process_id="close", step="s", principal="u", data_classification="internal", accountable_role="Controller")


class Crash(BaseException):
    """Stands in for the process dying: not an Exception, so nothing in the runtime catches it."""


class Ledger(Adapter):
    """Posts, records the posting, and replies; or does what ``script`` says for each call."""

    def __init__(self, p, *script, postings):
        super().__init__(p)
        self.script, self.postings = list(script), postings

    def call(self, payload, request):  # no adapter-side memory: only the control plane may prevent repeats
        return self.invoke(payload, request)

    def invoke(self, payload, request):
        then = self.script.pop(0) if self.script else "ok"
        if then == "refuse":
            raise DefiniteFailure("refused")
        self.postings.append(self.profile.supplier_id)
        if then == "crash":
            raise Crash()
        if then == "timeout":
            raise TimeoutError()
        return AdapterResult({"receipt_id": f"r{len(self.postings)}", "status": "completed", "compensation": "reverse"},
                             [{"type": "gl", "reference": "g"}])


def lp(aid):
    return profile(aid, capability="post-journal-entry", max_rclass=RClass.R2, max_data_classification="internal")


ROUTE = Route.from_dict({"opcp_version": "0.1", "capability": "post-journal-entry", "version": 1, "mode": "pinned",
                         "authored_by": "m", "approved_by": "c", "candidates": ["a", "b"]})


def plane(store, *adapters):
    return ControlPlane(CATALOGUE, list(adapters), [ROUTE], gate=AuthorityGate(budgets={"post-journal-entry": 9}),
                        today=TODAY, idempotency_store=store)


def test_a_completed_call_replays_after_a_restart(tmp_path):
    posted: list[str] = []
    path = tmp_path / "idem.jsonl"
    first = plane(FileIdempotencyStore(path), Ledger(lp("a"), postings=posted), Ledger(lp("b"), postings=posted))
    r1 = first.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    # restart: a new control plane over the same file
    second = plane(FileIdempotencyStore(path), Ledger(lp("a"), postings=posted), Ledger(lp("b"), postings=posted))
    r2 = second.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert posted == ["A"] and r2.ok and r2.output == r1.output and r2.trace_id == r1.trace_id
    other = {**JOURNAL, "entry_date": "2026-11-01"}
    assert second.call("post-journal-entry", other, idempotency_key="k", **JCALL).status == "rejected"


def test_without_a_file_a_restart_forgets_and_posts_again(tmp_path):
    # The default store is in memory: this is the behaviour the file store exists to prevent.
    posted: list[str] = []
    for _ in range(2):
        plane(IdempotencyStore(), Ledger(lp("a"), postings=posted), Ledger(lp("b"), postings=posted)).call(
            "post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert posted == ["A", "A"]


def test_a_crash_during_the_supplier_call_cannot_cause_a_second_posting_elsewhere(tmp_path):
    posted: list[str] = []
    path = tmp_path / "idem.jsonl"
    first = plane(FileIdempotencyStore(path), Ledger(lp("a"), "crash", postings=posted), Ledger(lp("b"), postings=posted))
    with pytest.raises(Crash):
        first.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    # After the restart, A is down: without the record written before the call, B would post again.
    second = plane(FileIdempotencyStore(path), Ledger(lp("a"), "timeout", postings=posted), Ledger(lp("b"), postings=posted))
    retry = second.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert retry.outcome == "unknown" and retry.supplier_id == "A" and "B" not in posted


def test_an_unknown_outcome_still_binds_the_key_after_a_restart(tmp_path):
    posted: list[str] = []
    path = tmp_path / "idem.jsonl"
    plane(FileIdempotencyStore(path), Ledger(lp("a"), "timeout", postings=posted), Ledger(lp("b"), postings=posted)).call(
        "post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    second = plane(FileIdempotencyStore(path), Ledger(lp("a"), postings=posted), Ledger(lp("b"), postings=posted))
    retry = second.call("post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert retry.ok and retry.supplier_id == "A" and posted == ["A", "A"]  # A deduplicates by key (spec 8.3)
    assert not second.idempotency.unresolved and len(second.idempotency.completed) == 1


def test_a_definite_failure_leaves_nothing_reserved(tmp_path):
    posted: list[str] = []
    store = FileIdempotencyStore(tmp_path / "idem.jsonl")
    r = plane(store, Ledger(lp("a"), "refuse", postings=posted), Ledger(lp("b"), postings=posted)).call(
        "post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert r.ok and r.supplier_id == "B" and not store.unresolved and posted == ["B"]


def test_checks_without_a_lasting_effect_write_no_reservations(tmp_path):
    class Check(Adapter):
        def invoke(self, payload, request):
            return AdapterResult({"verdict": "pass", "reason_codes": []}, [{"type": "r", "reference": "r"}], 0.9)

    route = Route.from_dict({"opcp_version": "0.1", "capability": "verify-identity", "version": 1, "mode": "pinned",
                             "authored_by": "m", "approved_by": "c", "candidates": ["c"]})
    path = tmp_path / "idem.jsonl"
    p = ControlPlane(CATALOGUE, [Check(profile("c"))], [route], today=TODAY, idempotency_store=FileIdempotencyStore(path))
    assert p.call("verify-identity", PERSON, idempotency_key="v", **CALL).ok
    kinds = [json.loads(line)["map"] for line in path.read_text().splitlines()]
    assert kinds == ["completed"]


def test_completed_records_expire_but_unresolved_ones_never_do(tmp_path):
    now = [dt.datetime(2026, 11, 16, tzinfo=dt.timezone.utc)]
    path = tmp_path / "idem.jsonl"
    store = FileIdempotencyStore(path, retention=dt.timedelta(days=7), clock=lambda: now[0])
    posted: list[str] = []
    p = plane(store, Ledger(lp("a"), "ok", "timeout", postings=posted), Ledger(lp("b"), postings=posted))
    p.call("post-journal-entry", JOURNAL, idempotency_key="done", **JCALL)
    p.call("post-journal-entry", {**JOURNAL, "entry_date": "2026-11-02"}, idempotency_key="open", **JCALL)
    now[0] += dt.timedelta(days=8)
    reopened = FileIdempotencyStore(path, retention=dt.timedelta(days=7), clock=lambda: now[0])
    assert not reopened.completed and len(reopened.unresolved) == 1
    assert len(path.read_text().splitlines()) == 1  # compacted on open
    assert ("post-journal-entry", "u", "open") in reopened.unresolved  # still binding, however old
    retry = plane(reopened, Ledger(lp("a"), "timeout", postings=posted), Ledger(lp("b"), postings=posted)).call(
        "post-journal-entry", {**JOURNAL, "entry_date": "2026-11-02"}, idempotency_key="open", **JCALL)
    assert retry.outcome == "unknown" and "B" not in posted


def test_the_file_is_private_and_survives_a_torn_last_line(tmp_path):
    path = tmp_path / "idem.jsonl"
    posted: list[str] = []
    plane(FileIdempotencyStore(path), Ledger(lp("a"), postings=posted), Ledger(lp("b"), postings=posted)).call(
        "post-journal-entry", JOURNAL, idempotency_key="k", **JCALL)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    with path.open("a") as fh:
        fh.write('{"at": "2026-11-16T00:00:00+00:00", "op": "put", "map": "comp')  # cut off by a crash
    reopened = FileIdempotencyStore(path)
    assert reopened.skipped_lines == 1 and len(reopened.completed) == 1


def test_compaction_keeps_exactly_the_live_records(tmp_path):
    path = tmp_path / "idem.jsonl"
    posted: list[str] = []
    store = FileIdempotencyStore(path)
    p = plane(store, Ledger(lp("a"), "refuse", "ok", "ok", postings=posted), Ledger(lp("b"), postings=posted))
    for i in range(3):
        p.call("post-journal-entry", {**JOURNAL, "entry_date": f"2026-11-0{i + 1}"}, idempotency_key=f"k{i}", **JCALL)
    before = len(path.read_text().splitlines())
    store.compact()
    after = FileIdempotencyStore(path)
    assert len(path.read_text().splitlines()) == 3 < before
    assert {k[2] for k in after.completed} == {"k0", "k1", "k2"} and not after.unresolved

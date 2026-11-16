"""The quick start must stay true: its example runs, prints what the guide shows, and each
"change something" step behaves as docs/QUICKSTART.md says."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import sys
from pathlib import Path

import pytest

from opcp._io import ValidationFailed
from opcp.conformance import check_adapter
from opcp.contract import Contract
from opcp.router import Route

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "quickstart"


def load_example():
    spec = importlib.util.spec_from_file_location("opcp_quickstart", EXAMPLE / "quickstart.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


QS = load_example()
CALL = dict(process_id="p", step="s", principal="agent", data_classification="confidential",
            accountable_role="Head of Onboarding", idempotency_key="k")


def test_output_matches_the_guide():
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        QS.main()
    guide = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    shown = re.search(r"You should see:\n\n```\n(.*?)```", guide, re.S).group(1)
    assert printed.getvalue() == shown


def test_example_adapter_passes_conformance():
    plane = QS.build()
    report = check_adapter(plane.adapters["watchlist-inhouse"], plane.contracts["screen-name"])
    assert report.passed, report.render()


def test_without_evidence_the_call_fails():
    plane = QS.build()
    adapter = plane.adapters["watchlist-inhouse"]
    original = adapter.invoke

    def no_evidence(payload, request):
        result = original(payload, request)
        result.evidence = []
        return result

    adapter.invoke = no_evidence
    assert plane.call("screen-name", {"full_name": "Alex Tan"}, **CALL).status == "failed"


def test_unapproved_supplier_is_not_eligible():
    plane = QS.build()
    adapter = plane.adapters["watchlist-inhouse"]
    object.__setattr__(adapter.profile, "approved", False)
    r = plane.call("screen-name", {"full_name": "Alex Tan"}, **CALL)
    assert r.status == "failed" and adapter.invocations == 0


def test_self_approved_route_is_refused():
    import yaml

    route = yaml.safe_load((EXAMPLE / "screen-name.route.yaml").read_text(encoding="utf-8"))
    route["approved_by"] = route["authored_by"]
    with pytest.raises(ValidationFailed, match="maker-checker"):
        Route.from_dict(route)


def test_r2_without_budget_or_approver_is_rejected_before_any_supplier():
    plane = QS.build()
    raw = dict(plane.contracts["screen-name"].raw, rclass="R2")
    plane.contracts["screen-name"] = Contract.from_dict(raw)
    r = plane.call("screen-name", {"full_name": "Alex Tan"}, **CALL)
    assert r.status == "rejected" and plane.adapters["watchlist-inhouse"].invocations == 0


def test_troubleshooting_quotes_real_messages():
    """Every message quoted in docs/TROUBLESHOOTING.md still exists in the code (… stands for a value)."""
    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "opcp").glob("*.py"))
    guide = (ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
    quoted = [m for row in guide.splitlines() if row.startswith("| ")
              for m in re.findall(r"`([^`]+)`", row.split("|")[1])]
    skip = {"opcp: command not found", "rejected", "failed"}
    checked = 0
    for message in quoted:
        if message in skip or message.startswith("ImportError"):
            continue
        for chunk in (c.strip(" .'%") for c in message.split("…")):
            if len(chunk) >= 4:
                assert chunk in source, f"{message!r}: {chunk!r} not found in opcp/"
                checked += 1
    assert checked >= 25

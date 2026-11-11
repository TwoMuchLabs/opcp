"""OPCP in one file: a contract, an adapter, a route, and calls through the control plane.

Run it from anywhere:  python examples/quickstart/quickstart.py
Nothing leaves your machine; the "supplier" is a function in this file.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from opcp.adapter import Adapter, AdapterResult, SupplierProfile
from opcp.contract import Contract
from opcp.eventlog import EventLog
from opcp.router import Route
from opcp.runtime import ControlPlane

HERE = Path(__file__).resolve().parent
WATCH_LIST = {"VLAD BLOCKED"}


# 1. An adapter connects one supplier to one contract (spec section 8). Here the supplier is an
#    in-house function; for a vendor it would call their API. It only ever sees leased fields.
class InHouseWatchList(Adapter):
    def invoke(self, payload, request):
        hit = payload["full_name"].upper() in WATCH_LIST
        return AdapterResult(
            output={"verdict": "fail" if hit else "pass", "reason_codes": ["WATCHLIST_HIT"] if hit else []},
            evidence=[{"type": "watchlist_version", "reference": "internal-2026-11"}],  # check needs evidence
            confidence=1.0,
        )


def build() -> ControlPlane:
    contract = Contract.load(HERE / "screen-name.yaml")
    profile = SupplierProfile(                     # what the business has approved about this supplier
        adapter_id="watchlist-inhouse", supplier_id="Compliance systems", kind="internal",
        capability="screen-name", contract_major=1, approved=True, conformance_passed=True,
        max_data_classification="confidential", regions=frozenset({"SG"}),
    )
    route = Route.load(HERE / "screen-name.route.yaml")
    return ControlPlane({contract.id: contract}, [InHouseWatchList(profile)], [route],
                        log=EventLog(), today=dt.date(2026, 11, 7))


def main() -> None:
    plane = build()
    common = dict(process_id="customer-onboarding", step="screen", principal="onboarding-agent",
                  data_classification="confidential", accountable_role="Head of Onboarding")

    # 2. A normal call. The salary field is not in the contract, so the supplier never sees it.
    r = plane.call("screen-name", {"full_name": "Alex Tan", "country": "SG", "salary": 120000},
                   idempotency_key="onb-1001", **common)
    print(f"1. {r.status}: verdict {r.output['verdict']} from {r.supplier_id}")
    request = next(e for e in plane.log.entries(r.trace_id) if e["kind"] == "request")
    print(f"   lent {request['leased_fields']}, withheld {request['withheld_fields']}")

    # 3. The same request again (a retry) is replayed, not repeated.
    again = plane.call("screen-name", {"full_name": "Alex Tan", "country": "SG", "salary": 120000},
                       idempotency_key="onb-1001", **common)
    print(f"2. retry with the same key: {again.status}, same trace: {again.trace_id == r.trace_id}")

    # 4. Data outside the supplier's regions is never sent: the request allows only Malaysia.
    r = plane.call("screen-name", {"full_name": "Alex Tan"}, idempotency_key="onb-1002", residency=["MY"], **common)
    print(f"3. residency MY: {r.status} ({r.error})")

    # 5. A capability with no contract fails closed, as the highest Reversibility Class.
    r = plane.call("wire-funds", {"amount": 1_000_000}, idempotency_key="x-1", **common)
    print(f"4. unknown capability: {r.status} as {r.rclass}")

    print(f"Event log: {len(plane.log)} entries, every gate decision included.")


if __name__ == "__main__":
    main()

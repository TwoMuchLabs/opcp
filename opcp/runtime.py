"""The reference control plane: gate, lease, route, invoke, record (spec sections 9-11)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from typing import Any, Iterable, Mapping, Sequence

from .adapter import Adapter
from .contract import Contract
from .envelope import CLASSIFICATIONS, Request, Response, classification_rank
from .eventlog import EventLog
from .gate import AuthorityGate, GateResult
from .router import Route, concentration, eligible, exclusion_reasons, order


class ConfigurationError(ValueError):
    """The control plane's contracts, adapters and routes do not fit together."""


def _fingerprint(capability_id: str, payload: Mapping[str, Any]) -> str:
    text = json.dumps({"c": capability_id, "p": payload}, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


class ControlPlane:
    """Reference implementation of an OPCP runtime.

    ``require_accountable_role`` enforces spec 10.5: every call must name the accountable human role.
    ``store_values`` controls whether input and output values reach the event log; by default only
    field names do, and validation or supplier error messages are redacted.
    """

    def __init__(
        self,
        contracts: Mapping[str, Contract],
        adapters: Iterable[Adapter],
        routes: Iterable[Route],
        gate: AuthorityGate | None = None,
        log: EventLog | None = None,
        concentration_limit: float | None = None,
        today: dt.date | None = None,
        store_values: bool = False,
        require_accountable_role: bool = True,
    ):
        self.contracts = dict(contracts)
        self.adapters = {a.profile.adapter_id: a for a in adapters}
        self.routes = {r.capability: r for r in routes}
        self.gate = gate if gate is not None else AuthorityGate()
        self.log = log if log is not None else EventLog()  # an empty log is falsy, so test for None
        self.today = today
        self.store_values = store_values
        self.require_accountable_role = require_accountable_role
        self._responses: dict[tuple[str, str, str], tuple[str, Response]] = {}
        self._check_configuration(concentration_limit)

    # ------------------------------------------------------------ setup

    def _check_configuration(self, limit: float | None) -> None:
        problems = []
        for cap, route in self.routes.items():
            contract = self.contracts.get(cap)
            if contract is None:
                problems.append(f"route for {cap!r} has no contract")
                continue
            ids = set(route.candidates) | {i for ids in route.segments.values() for i in ids}
            if route.escalation:
                ids.add(route.escalation)
            for adapter_id in sorted(ids):
                adapter = self.adapters.get(adapter_id)
                if adapter is None:
                    problems.append(f"route for {cap!r} names unknown adapter {adapter_id!r}")
                elif adapter.profile.capability != cap:
                    problems.append(f"adapter {adapter_id!r} fulfils {adapter.profile.capability!r}, not {cap!r}")
        if problems:
            raise ConfigurationError("; ".join(problems))
        if limit is not None:
            breaches = concentration(list(self.routes.values()), self.adapters, limit)
            if breaches:
                detail = "; ".join(f"{b.supplier_id} is primary for {b.share:.0%} of critical routes ({', '.join(b.capabilities)})" for b in breaches)
                raise ConfigurationError(f"concentration limit {limit:.0%} breached: {detail}")

    # ------------------------------------------------------------ call

    def call(
        self,
        capability_id: str,
        payload: Mapping[str, Any],
        *,
        process_id: str,
        step: str,
        principal: str,
        data_classification: str,
        idempotency_key: str,
        residency: Sequence[str] | None = None,
        segment: str | None = None,
        accountable_role: str | None = None,
    ) -> Response:
        # Idempotency is scoped to the capability and principal, and bound to the payload.
        cache_key = (capability_id, principal, idempotency_key)
        fingerprint = _fingerprint(capability_id, payload)
        if cache_key in self._responses:
            seen, previous = self._responses[cache_key]
            if seen == fingerprint:
                self.log.append("replay", previous.trace_id, idempotency_key=idempotency_key)
                return previous

        started = time.perf_counter()
        contract = self.contracts.get(capability_id)
        request = Request(
            capability_id=capability_id,
            capability_version=contract.version if contract else "unknown",
            process_id=process_id,
            step=step,
            principal=principal,
            input={},
            data_classification=data_classification,
            idempotency_key=idempotency_key,
            residency=tuple(residency) if residency is not None else None,
            segment=segment,
        )
        trace = request.trace_id

        def finish(response: Response, gate: GateResult | None = None) -> Response:
            response.latency_ms = (time.perf_counter() - started) * 1000
            if gate is not None and response.status not in ("ok", "escalated"):
                self.gate.refund(gate, capability_id)
            out = response.to_dict()
            if not self.store_values and "output" in out:
                out["output"] = sorted(out["output"])
            self.log.append("response", trace, response=out)
            # Only completed work is remembered; a rejection or failure may be retried with the same key.
            if response.status in ("ok", "escalated"):
                self._responses[cache_key] = (fingerprint, response)
            return response

        def stop(status: str, rclass: str, reason: str, error: str, mode: str = "none", gate: GateResult | None = None) -> Response:
            return finish(Response(trace, status, rclass, mode, reason, 0, error=error), gate)

        if cache_key in self._responses:  # same key, different payload
            self.log.append("request", trace, request=request.to_dict(values=False))
            return stop("rejected", str(contract.rclass) if contract else "R4", "idempotency",
                        "idempotency key already used for a different input")

        if contract is None:  # fail closed (spec 10.2) and record the gate decision (spec 10.6)
            self.log.append("request", trace, request=request.to_dict(values=False))
            self.log.append("gate", trace, allowed=False, rclass="R4", decision="never_autonomous",
                            reason="no contract; fail closed", approved_by=[], notify=False, accountable_role=accountable_role)
            return stop("rejected", "R4", "no contract", f"no contract for {capability_id!r}; treated as R4")

        # Context lease (spec 11.2)
        leased, withheld = contract.lease(dict(payload))
        request.input = leased
        self.log.append("request", trace, request=request.to_dict(values=self.store_values),
                        leased_fields=sorted(leased), withheld_fields=withheld)

        problems: list[str] = []
        if data_classification not in CLASSIFICATIONS:
            problems.append(f"unknown data classification {data_classification!r}")
        elif classification_rank(data_classification) > classification_rank(contract.data_classification):
            problems.append(f"input is {data_classification}; contract accepts at most {contract.data_classification}")
        if self.require_accountable_role and not accountable_role:
            problems.append("no accountable human role named for this step (spec 10.5)")
        problems += contract.input_errors(leased, redact=not self.store_values)
        if problems:
            return stop("failed", str(contract.rclass), "invalid request", "; ".join(problems))

        # Authority gate before any supplier (spec 10)
        verdict = self.gate.decide(contract, request, accountable_role)
        self.log.append("gate", trace, **verdict.to_dict())
        if not verdict.allowed:
            return stop("rejected", str(verdict.rclass), "authority gate", verdict.reason)

        route = self.routes.get(capability_id)
        if route is None:
            return stop("failed", str(verdict.rclass), "no route", f"no route for {capability_id!r}", gate=verdict)

        today = self.today or dt.date.today()
        candidate_ids = list(dict.fromkeys([*route.candidates, *[i for ids in route.segments.values() for i in ids]]))
        pool, excluded = eligible([self.adapters[i] for i in candidate_ids], contract, request, today, verdict.rclass)
        try:
            ranked, why = order(route, contract, pool, request, verdict.rclass)
        except ValueError as exc:
            return stop("failed", str(verdict.rclass), "routing refused", str(exc), route.mode, gate=verdict)
        self.log.append("route", trace, mode=route.mode, route_version=route.version, reason=why,
                        order=[a.profile.adapter_id for a in ranked], excluded=excluded)

        attempts: list[str] = []
        for adapter in ranked:
            response = self._attempt(adapter, contract, request, leased, route, why, verdict, attempts)
            if response is not None:
                return finish(response, verdict)

        # Escalation (spec 9.1, 9.3)
        if route.escalation and route.escalation not in {a.profile.adapter_id for a in ranked}:
            esc = self.adapters[route.escalation]
            reasons = exclusion_reasons(esc, contract, request, today, verdict.rclass)
            if not reasons:
                response = self._attempt(esc, contract, request, leased, route, "escalated to " + esc.profile.adapter_id,
                                         verdict, attempts, escalation=True)
                if response is not None:
                    return finish(response, verdict)
            else:
                attempts.append(f"{esc.profile.adapter_id}: escalation supplier not eligible ({'; '.join(reasons)})")

        detail = "; ".join(attempts) or "no eligible supplier: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in excluded.items())
        return stop("failed", str(verdict.rclass), why, detail, route.mode, gate=verdict)

    def _attempt(self, adapter: Adapter, contract: Contract, request: Request, leased: dict, route: Route, why: str,
                 verdict: GateResult, attempts: list[str], escalation: bool = False) -> Response | None:
        aid = adapter.profile.adapter_id
        trace = request.trace_id
        try:
            result = adapter.call(dict(leased), request)
        except Exception as exc:  # a supplier failure triggers failover, never a crash
            detail = str(exc) if self.store_values else type(exc).__name__
            attempts.append(f"{aid}: error ({detail})")
            self.log.append("attempt", trace, adapter=aid, outcome="error", detail=detail)
            return None
        problems = contract.output_errors(result.output)
        if contract.evidence_required and not result.evidence:
            problems.append("evidence required but none returned")
        if problems:
            adapter.forget(dict(leased), request)
            shown = problems if self.store_values else [p.split(":")[0] + ": invalid" for p in problems]
            attempts.append(f"{aid}: invalid output ({'; '.join(shown)})")
            self.log.append("attempt", trace, adapter=aid, outcome="invalid", detail=shown)
            return None
        threshold = route.cascade_min_confidence
        human = adapter.profile.kind == "human"  # people decide; they do not report a model confidence
        if route.mode == "cascade" and not escalation and not human and threshold is not None \
                and (result.confidence is None or result.confidence < threshold):
            adapter.forget(dict(leased), request)
            attempts.append(f"{aid}: confidence {result.confidence} below {threshold}")
            self.log.append("attempt", trace, adapter=aid, outcome="low_confidence", confidence=result.confidence)
            return None
        self.log.append("attempt", trace, adapter=aid, outcome="ok", confidence=result.confidence)
        cost = None if result.cost is None else {"amount": result.cost, "currency": adapter.profile.currency}
        reason = why if not attempts else f"{why}; after {len(attempts)} unsuccessful attempt(s)"
        return Response(
            trace_id=trace,
            status="escalated" if escalation or (human and route.mode == "cascade") else "ok",
            rclass=str(verdict.rclass),
            route_mode=route.mode,
            route_reason=reason,
            latency_ms=0,
            output=result.output,
            evidence=list(result.evidence),
            confidence=result.confidence,
            cost=cost,
            supplier_id=adapter.profile.supplier_id,
            adapter_version=adapter.profile.adapter_version,
        )

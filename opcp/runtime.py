"""The reference control plane: gate, lease, route, invoke, record (spec sections 9-11)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .adapter import Adapter, DefiniteFailure
from .contract import Contract
from .envelope import CLASSIFICATIONS, Request, Response, classification_rank
from .eventlog import EventLog
from .gate import AuthorityGate, GateResult
from .idempotency import IdempotencyStore
from .rclass import RClass
from .router import Route, concentration, eligible, exclusion_reasons, order


class ConfigurationError(ValueError):
    """The control plane's contracts, adapters and routes do not fit together."""


# Archetypes whose effect outlasts the call: a repeat posts, pays, books or sends twice.
EFFECT_ARCHETYPES = frozenset({"transact", "notify"})


def has_lasting_effect(contract: Contract, rclass: RClass) -> bool:
    """Whether repeating this call at another supplier could repeat an effect that matters.

    True for Reversibility Class R2 and above, and for the ``transact`` and ``notify`` archetypes. For such
    calls the runtime never moves to another supplier after an attempt whose outcome is unknown (issue #27).
    """
    return rclass >= RClass.R2 or contract.archetype in EFFECT_ARCHETYPES


def _fingerprint(capability_id: str, payload: Mapping[str, Any]) -> str:
    text = json.dumps({"c": capability_id, "p": payload}, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class _Unknown:
    """An attempt after which the supplier may have acted, though the runtime cannot accept its result."""

    adapter: Adapter
    detail: str


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
        idempotency_store: IdempotencyStore | None = None,
        shadow_workers: int = 2,
        shadow_queue_limit: int = 100,
    ):
        self.contracts = dict(contracts)
        self.adapters = {a.profile.adapter_id: a for a in adapters}
        self.routes = {r.capability: r for r in routes}
        self.gate = gate if gate is not None else AuthorityGate()
        self.log = log if log is not None else EventLog()  # an empty log is falsy, so test for None
        self.today = today
        self.store_values = store_values
        self.require_accountable_role = require_accountable_role
        # Idempotency records (spec 7.1). In memory by default; a FileIdempotencyStore keeps them across restarts.
        self.idempotency = idempotency_store if idempotency_store is not None else IdempotencyStore()
        # Completed responses: key -> (input fingerprint, response).
        self._responses = self.idempotency.completed
        # Keys where a supplier with a lasting effect may have acted and the outcome is not known: key ->
        # (input fingerprint, adapter id, supplier id). A retry goes back to that supplier and no other (#27).
        # Written before each such call, so a crash mid-call leaves the same protection.
        self._unresolved = self.idempotency.unresolved
        # One call at a time per idempotency key, so concurrent duplicates cannot both reach a supplier.
        self._key_locks: dict[tuple[str, str, str], list] = {}  # key -> [lock, number of callers holding or waiting]
        self._key_locks_guard = threading.Lock()
        # Shadow calls run in the background, so the live caller never waits for them (spec 9.6).
        self._shadow_workers = shadow_workers
        # A slow shadow supplier must not pile up work (and copies of leased data) without limit.
        self._shadow_queue_limit = shadow_queue_limit
        self._shadow_pool: ThreadPoolExecutor | None = None
        self._shadow_pending: set[Future] = set()
        self._shadow_guard = threading.Lock()
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
            if route.shadow:
                ids.add(route.shadow.adapter)
            for adapter_id in sorted(ids):
                adapter = self.adapters.get(adapter_id)
                if adapter is None:
                    problems.append(f"route for {cap!r} names unknown adapter {adapter_id!r}")
                elif adapter.profile.capability != cap:
                    problems.append(f"adapter {adapter_id!r} fulfils {adapter.profile.capability!r}, not {cap!r}")
        for cap, raised in sorted(getattr(self.gate, "overrides", {}).items()):
            contract = self.contracts.get(cap)
            if contract is not None and raised < contract.rclass:
                problems.append(f"gate override would lower {cap!r} from {contract.rclass} to {raised}; "
                                "overrides may only raise (spec 10.1)")
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
        """Make one capability call through the gate, lease, router and event log.

        Calls that share a capability, principal and idempotency key are serialised: a second call with
        the same key waits for the first, then replays its result (or is refused if its input differs).
        Calls with different keys run concurrently.
        """
        key = (capability_id, principal, idempotency_key)
        with self._key_locks_guard:
            entry = self._key_locks.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                return self._call(capability_id, payload, process_id=process_id, step=step, principal=principal,
                                  data_classification=data_classification, idempotency_key=idempotency_key,
                                  residency=residency, segment=segment, accountable_role=accountable_role)
        finally:
            with self._key_locks_guard:
                entry[1] -= 1
                if entry[1] == 0:
                    del self._key_locks[key]

    def _call(
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

        pending = self._unresolved.get(cache_key)
        if cache_key in self._responses or (pending is not None and pending[0] != fingerprint):
            # Same key, different payload. After an unknown outcome the key stays bound to its first input,
            # because the supplier may have acted on it.
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
        try:
            verdict = self.gate.decide(contract, request, accountable_role)
        except Exception as exc:  # a gate that cannot decide refuses, and the refusal is logged (spec 10.2, 10.6)
            detail = str(exc) if self.store_values else type(exc).__name__
            self.log.append("gate", trace, allowed=False, rclass="R4", decision="never_autonomous",
                            reason=f"gate error ({detail}); fail closed", approved_by=[], notify=False,
                            accountable_role=accountable_role)
            return stop("rejected", "R4", "authority gate", f"gate error ({detail}); fail closed")
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

        attempts: list[str] = []
        effectful = has_lasting_effect(contract, verdict.rclass)

        def unknown(adapter: Adapter, detail: str, gate: GateResult | None = None) -> Response:
            """Stop after an attempt whose outcome is unknown; never try another supplier (issue #27).

            The key stays bound to this supplier, so a retry with it goes back there and nowhere else. The
            budget unit is kept (``gate`` is None) because the supplier may have used the authority it bounds.
            """
            aid = adapter.profile.adapter_id
            self._unresolved[cache_key] = (fingerprint, aid, adapter.profile.supplier_id)
            message = "; ".join([*attempts, f"outcome unknown at {aid}: {detail}"]) + (
                f". The supplier may have acted, so no other supplier was tried. Reconcile with {adapter.profile.supplier_id}, "
                f"or retry with the same idempotency key, which goes back to {aid} only")
            return finish(Response(trace, "failed", str(verdict.rclass), route.mode, why, 0, error=message,
                                   supplier_id=adapter.profile.supplier_id, adapter_version=adapter.profile.adapter_version,
                                   outcome="unknown"), gate)

        # A retry after an unknown outcome goes to the same supplier first, and only on to others if that
        # supplier now reports a definite failure (it did nothing under this key).
        reserved: Adapter | None = None
        if pending is not None:
            reserved = self.adapters.get(pending[1])
            reasons = (exclusion_reasons(reserved, contract, request, today, verdict.rclass)
                       if reserved is not None else ["no longer configured"])
            if reserved is None or reasons:
                self.log.append("route", trace, mode=route.mode, route_version=route.version, reason=why,
                                order=[], excluded={**excluded, pending[1]: reasons})
                if reserved is None:
                    return finish(Response(trace, "failed", str(verdict.rclass), route.mode, why, 0,
                                           error=f"outcome unknown at {pending[1]}: an earlier attempt with this key may "
                                                 f"have acted, and that adapter is no longer configured. Reconcile with {pending[2]}",
                                           supplier_id=pending[2], adapter_version="unknown", outcome="unknown"), verdict)
                return unknown(reserved, "an earlier attempt with this key may have acted, and the supplier is not "
                               f"eligible now ({'; '.join(reasons)})", gate=verdict)
            ranked = [reserved, *[a for a in ranked if a is not reserved]]
            why = f"retry to {pending[1]} after an unknown outcome; then {why}"

        self.log.append("route", trace, mode=route.mode, route_version=route.version, reason=why,
                        order=[a.profile.adapter_id for a in ranked], excluded=excluded)

        def reserve(adapter: Adapter) -> None:
            """Before calling a supplier with a lasting effect, record that it may be about to act."""
            if effectful:
                self._unresolved[cache_key] = (fingerprint, adapter.profile.adapter_id, adapter.profile.supplier_id)

        def resolved(response: Response) -> Response:
            done = finish(response, verdict)  # the completed record is written first ...
            self._unresolved.pop(cache_key, None)  # ... so there is no moment when the key protects nothing
            return done

        for adapter in ranked:
            reserve(adapter)
            result = self._attempt(adapter, contract, request, leased, route, why, verdict, attempts, effectful=effectful)
            if isinstance(result, _Unknown):
                return unknown(result.adapter, result.detail)
            if result is not None:
                done = resolved(result)  # the live response is complete before any shadow work
                self._shadow(route, contract, request, leased, withheld, done, adapter, verdict, today)
                return done
            if effectful or adapter is reserved:  # a definite failure: nothing happened under this key there
                self._unresolved.pop(cache_key, None)

        # Escalation (spec 9.1, 9.3)
        if route.escalation and route.escalation not in {a.profile.adapter_id for a in ranked}:
            esc = self.adapters[route.escalation]
            reasons = exclusion_reasons(esc, contract, request, today, verdict.rclass)
            if not reasons:
                reserve(esc)
                result = self._attempt(esc, contract, request, leased, route, "escalated to " + esc.profile.adapter_id,
                                       verdict, attempts, escalation=True, effectful=effectful)
                if isinstance(result, _Unknown):
                    return unknown(result.adapter, result.detail)
                if result is not None:
                    return resolved(result)
                self._unresolved.pop(cache_key, None)
            else:
                attempts.append(f"{esc.profile.adapter_id}: escalation supplier not eligible ({'; '.join(reasons)})")

        detail = "; ".join(attempts) or "no eligible supplier: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in excluded.items())
        return stop("failed", str(verdict.rclass), why, detail, route.mode, gate=verdict)

    def _attempt(self, adapter: Adapter, contract: Contract, request: Request, leased: dict, route: Route, why: str,
                 verdict: GateResult, attempts: list[str], escalation: bool = False,
                 effectful: bool = False) -> Response | _Unknown | None:
        """Try one supplier. ``None`` means it certainly did nothing, so the next one may be tried.

        With ``effectful`` (see :func:`has_lasting_effect`), an error other than :class:`DefiniteFailure`, an
        invalid output, or a confidence below a cascade threshold means the supplier may have acted, and the
        attempt returns :class:`_Unknown` instead of letting the caller fail over (issue #27).
        """
        aid = adapter.profile.adapter_id
        trace = request.trace_id
        try:
            result = adapter.call(dict(leased), request)
        except Exception as exc:  # a supplier failure never crashes the call
            detail = str(exc) if self.store_values else type(exc).__name__
            if effectful and not isinstance(exc, DefiniteFailure):
                self.log.append("attempt", trace, adapter=aid, outcome="unknown", detail=detail)
                return _Unknown(adapter, f"no confirmed reply ({detail})")
            attempts.append(f"{aid}: error ({detail})")
            self.log.append("attempt", trace, adapter=aid, outcome="error", detail=detail)
            return None
        problems = contract.output_errors(result.output)
        if contract.evidence_required and not result.evidence:
            problems.append("evidence required but none returned")
        if problems:
            adapter.forget(dict(leased), request)  # so a retry with the same key reaches the supplier again
            shown = problems if self.store_values else [p.split(":")[0] + ": invalid" for p in problems]
            if effectful:
                self.log.append("attempt", trace, adapter=aid, outcome="unknown", detail=shown)
                return _Unknown(adapter, f"invalid output ({'; '.join(shown)})")
            attempts.append(f"{aid}: invalid output ({'; '.join(shown)})")
            self.log.append("attempt", trace, adapter=aid, outcome="invalid", detail=shown)
            return None
        threshold = route.cascade_min_confidence
        human = adapter.profile.kind == "human"  # people decide; they do not report a model confidence
        if route.mode == "cascade" and not escalation and not human and threshold is not None \
                and (result.confidence is None or result.confidence < threshold):
            adapter.forget(dict(leased), request)
            if effectful:
                self.log.append("attempt", trace, adapter=aid, outcome="unknown", confidence=result.confidence)
                return _Unknown(adapter, f"confidence {result.confidence} below {threshold}")
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

    # ------------------------------------------------------------ shadow (spec 9.6)

    def wait_for_shadows(self, timeout: float | None = None) -> bool:
        """Block until every shadow call started so far has been recorded. Returns False on timeout.

        Live calls never wait for shadow work; use this before exporting the log or shutting down.
        """
        with self._shadow_guard:
            pending = set(self._shadow_pending)
        done, not_done = wait(pending, timeout=timeout)
        return not not_done

    def close(self) -> None:
        """Finish outstanding shadow calls and stop the background workers."""
        with self._shadow_guard:
            pool, self._shadow_pool = self._shadow_pool, None
        if pool is not None:
            pool.shutdown(wait=True)

    def _shadow(self, route: Route, contract: Contract, request: Request, leased: dict, withheld: list[str],
                live: Response, served_by: Adapter, verdict: GateResult, today: dt.date) -> None:
        """Decide whether this request is copied to the route's shadow supplier, and if so, start it.

        Checks that need no supplier happen here and are logged at once. The shadow call itself runs on a
        background worker, so it adds nothing to the live call's time, and nothing it does or raises can
        reach the caller.
        """
        spec = route.shadow
        if spec is None or live.status != "ok" or not spec.selects(request.idempotency_key):
            return
        trace = request.trace_id
        aid = spec.adapter
        base = {"capability": contract.id, "adapter": aid, "live_adapter": served_by.profile.adapter_id}
        try:
            if aid == served_by.profile.adapter_id:
                self.log.append("shadow", trace, **base, outcome="skipped", reason="the shadow supplier served the live request")
                return
            if verdict.rclass > RClass.R0:  # a copy of an action is still an action (SWAP-DRILL 2)
                self.log.append("shadow", trace, **base, outcome="skipped",
                                reason=f"shadow runs only for R0; gate applied {verdict.rclass}")
                return
            adapter = self.adapters[aid]
            reasons = exclusion_reasons(adapter, contract, request, today, verdict.rclass)
            if reasons:  # copying data to a supplier that is not eligible would be a disclosure
                self.log.append("shadow", trace, **base, outcome="skipped", reason="not eligible: " + "; ".join(reasons))
                return
            # Private copies: the caller may change its objects once the live response is returned.
            payload = json.loads(json.dumps(leased, default=str))
            live_output = json.loads(json.dumps(live.output or {}, default=str))
            with self._shadow_guard:  # check and submit together, so concurrent calls can't overshoot the limit
                future = None
                if len(self._shadow_pending) < self._shadow_queue_limit:
                    if self._shadow_pool is None:
                        self._shadow_pool = ThreadPoolExecutor(max_workers=self._shadow_workers,
                                                               thread_name_prefix="opcp-shadow")
                    future = self._shadow_pool.submit(self._run_shadow, spec, contract, request, payload, withheld,
                                                      live_output, live.confidence, base)
                    self._shadow_pending.add(future)
            if future is None:
                self.log.append("shadow", trace, **base, outcome="skipped",
                                reason=f"shadow queue full ({self._shadow_queue_limit} calls waiting)")
                return
            future.add_done_callback(self._shadow_finished)
        except Exception as exc:  # nothing about the shadow may change the live response
            self._log_shadow_error(trace, base, exc)

    def _shadow_finished(self, future: Future) -> None:
        with self._shadow_guard:
            self._shadow_pending.discard(future)

    def _log_shadow_error(self, trace: str, base: dict, exc: BaseException) -> None:
        try:
            detail = str(exc) if self.store_values else type(exc).__name__
            self.log.append("shadow", trace, **base, outcome="error", detail=detail)
        except Exception:  # the log itself failed; there is nowhere left to record it
            pass

    def _run_shadow(self, spec, contract: Contract, request: Request, payload: dict, withheld: list[str],
                    live_out: dict, live_confidence: float | None, base: dict) -> None:
        """The shadow call and its comparison, on a background worker. Every outcome is logged; nothing raises."""
        trace = request.trace_id
        adapter = self.adapters[spec.adapter]
        # The shadow supplier gets the same lease as the live one, and the log says so (spec 11.2).
        base = {**base, "leased_fields": sorted(payload), "withheld_fields": withheld}
        try:
            started = time.perf_counter()
            try:
                result = adapter.call(dict(payload), request)
            except Exception as exc:
                self._log_shadow_error(trace, base, exc)
                return
            latency = (time.perf_counter() - started) * 1000
            problems = contract.output_errors(result.output)
            if contract.evidence_required and not result.evidence:
                problems.append("evidence required but none returned")
            if problems:
                shown = problems if self.store_values else [p.split(":")[0] + ": invalid" for p in problems]
                self.log.append("shadow", trace, **base, outcome="invalid", detail=shown, latency_ms=latency)
                adapter.forget(dict(payload), request)  # last: a forget() that raises is caught below
                return
            declared = list(contract.output_schema.get("properties", {}))
            fields = list(spec.compare) or declared or sorted(set(live_out) | set(result.output))
            agreed = [f for f in fields if live_out.get(f) == result.output.get(f)]
            disagreed = [f for f in fields if f not in agreed]
            entry = {**base, "outcome": "ok", "agreed": agreed, "disagreed": disagreed,
                     "confidence": result.confidence, "live_confidence": live_confidence,
                     "latency_ms": latency, "cost": result.cost}
            if self.store_values:
                entry["differences"] = {f: {"live": live_out.get(f), "shadow": result.output.get(f)} for f in disagreed}
            self.log.append("shadow", trace, **entry)
        except Exception as exc:
            self._log_shadow_error(trace, base, exc)

"""Two-stage routing: eligibility, then selection (spec section 9)."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ._io import ValidationFailed, errors, load_document, schema_validator
from .adapter import Adapter
from .contract import Contract
from .envelope import Request, classification_rank
from .rclass import RClass

MODES = ("pinned", "segmented", "cascade", "weighted", "best_score")


@dataclass(frozen=True)
class ShadowSpec:
    """Send copies of requests to an alternative supplier and compare, without acting on its result (spec 9.6)."""

    adapter: str
    sample: float = 1.0
    compare: tuple[str, ...] = ()

    def selects(self, idempotency_key: str) -> bool:
        """Deterministic sampling, so the same request is always in or out of the drill."""
        if self.sample >= 1.0:
            return True
        point = int(hashlib.sha256(f"shadow\x1f{idempotency_key}".encode()).hexdigest(), 16) % 10_000 / 10_000
        return point < self.sample


@dataclass(frozen=True)
class Route:
    capability: str
    version: int
    mode: str
    approved_by: str
    candidates: tuple[str, ...]
    critical: bool = False
    authored_by: str | None = None
    segments: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    weights: Mapping[str, float] = field(default_factory=dict)
    cascade_min_confidence: float | None = None
    selection_weights: Mapping[str, float] = field(default_factory=dict)
    escalation: str | None = None
    concentration_exception: str | None = None
    shadow: ShadowSpec | None = None

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> "Route":
        problems = errors(schema_validator("route"), doc)
        if not problems:
            stray = sorted(set(doc.get("weights", {})) - set(doc["candidates"]))
            problems += [f"weights: {k!r} is not a candidate" for k in stray]
            shadow = doc.get("shadow")
            if shadow and shadow["adapter"] in doc["candidates"][:1]:
                problems.append("shadow: the shadow supplier must not be the primary candidate")
        if problems:
            raise ValidationFailed(f"route for {doc.get('capability', '?')!r}", problems)
        if doc["authored_by"] == doc["approved_by"]:
            raise ValidationFailed(f"route for {doc['capability']!r}", ["approved_by must differ from authored_by (maker-checker)"])
        return cls(
            capability=doc["capability"],
            version=doc["version"],
            mode=doc["mode"],
            approved_by=doc["approved_by"],
            candidates=tuple(doc["candidates"]),
            critical=bool(doc.get("critical", False)),
            authored_by=doc.get("authored_by"),
            segments={k: tuple(v) for k, v in doc.get("segments", {}).items()},
            weights=dict(doc.get("weights", {})),
            cascade_min_confidence=doc.get("cascade_min_confidence"),
            selection_weights=dict(doc.get("selection_weights", {})),
            escalation=doc.get("escalation"),
            concentration_exception=doc.get("concentration_exception"),
            shadow=(ShadowSpec(doc["shadow"]["adapter"], float(doc["shadow"].get("sample", 1.0)),
                               tuple(doc["shadow"].get("compare", ()))) if doc.get("shadow") else None),
        )

    @classmethod
    def load(cls, path: str | Path) -> "Route":
        return cls.from_dict(load_document(path))

    def primary_for(self, segment: str | None = None) -> str:
        if self.mode == "segmented" and segment in self.segments:
            return self.segments[segment][0]
        return self.candidates[0]


# ---------------------------------------------------------------- stage 1


def exclusion_reasons(adapter: Adapter, contract: Contract, request: Request, today: dt.date,
                      rclass: RClass | None = None) -> list[str]:
    """Every eligibility filter the adapter fails (spec 9.1). Empty means eligible.

    ``rclass`` is the class the authority gate applied, which may be higher than the contract's.
    """
    rclass = contract.rclass if rclass is None else rclass
    p = adapter.profile
    reasons: list[str] = []
    if p.capability != contract.id:
        reasons.append(f"fulfils {p.capability!r}, not {contract.id!r}")
    if not p.approved:
        reasons.append("not approved in the third-party register")
    if p.contract_end is not None and p.contract_end < today:
        reasons.append(f"supplier contract ended {p.contract_end.isoformat()}")
    if not p.conformance_passed or p.contract_major != contract.major:
        reasons.append(f"has not passed conformance for contract v{contract.major}")
    if classification_rank(request.data_classification) > classification_rank(p.max_data_classification):
        reasons.append(f"not permitted to process {request.data_classification} data")
    if request.residency is not None:
        if not p.regions:
            reasons.append("processing regions not declared")
        elif not set(p.regions) <= set(request.residency):
            outside = sorted(set(p.regions) - set(request.residency))
            reasons.append(f"processes data outside permitted regions ({', '.join(outside)})")
    if rclass > p.max_rclass:
        reasons.append(f"not authorised for {rclass} actions (max {p.max_rclass})")
    if not adapter.healthy():
        reasons.append("unhealthy or at capacity")
    return reasons


def eligible(adapters: Sequence[Adapter], contract: Contract, request: Request, today: dt.date,
             rclass: RClass | None = None) -> tuple[list[Adapter], dict[str, list[str]]]:
    keep, excluded = [], {}
    for adapter in adapters:
        reasons = exclusion_reasons(adapter, contract, request, today, rclass)
        if reasons:
            excluded[adapter.profile.adapter_id] = reasons
        else:
            keep.append(adapter)
    return keep, excluded


# ---------------------------------------------------------------- stage 2


def selection_score(adapter: Adapter, request: Request, weights: Mapping[str, float], pool: Sequence[Adapter]) -> float:
    """Weighted score: quality up, cost and latency down, each normalised across the pool."""
    w_q, w_c, w_l = weights.get("quality", 1.0), weights.get("cost", 0.0), weights.get("latency", 0.0)
    max_cost = max((a.profile.cost_per_call for a in pool), default=0.0) or 1.0
    max_lat = max((a.profile.latency_ms_p95 for a in pool), default=0.0) or 1.0
    p = adapter.profile
    return w_q * p.quality_for(request.segment) - w_c * p.cost_per_call / max_cost - w_l * p.latency_ms_p95 / max_lat


def order(route: Route, contract: Contract, pool: Sequence[Adapter], request: Request,
          rclass: RClass | None = None) -> tuple[list[Adapter], str]:
    """Order eligible adapters to try, and explain why."""
    rclass = contract.rclass if rclass is None else rclass
    by_id = {a.profile.adapter_id: a for a in pool}

    def in_order(ids: Sequence[str]) -> list[Adapter]:
        return [by_id[i] for i in ids if i in by_id]

    if route.mode == "pinned":
        ranked = in_order(route.candidates)
        return ranked, "primary, then fallbacks in order"
    if route.mode == "segmented":
        # The segment's suppliers first, then the default candidates as fallbacks (spec 9.3).
        ids = [*route.segments.get(request.segment or "", ()), *route.candidates]
        label = request.segment if request.segment in route.segments else "default"
        return in_order(list(dict.fromkeys(ids))), f"segment {label!r}, default candidates as fallback"
    if route.mode == "cascade":
        return in_order(route.candidates), f"minimum confidence {route.cascade_min_confidence}"
    if route.mode == "weighted":
        ranked = in_order(route.candidates)
        weighted = [a for a in ranked if a.profile.adapter_id in route.weights]
        if not weighted:
            return ranked, "no weighted candidate eligible; candidate order"
        total = sum(route.weights[a.profile.adapter_id] for a in weighted)
        # Deterministic per request, so a retry lands on the same supplier.
        point = int(hashlib.sha256(request.idempotency_key.encode()).hexdigest(), 16) % 10_000 / 10_000 * total
        chosen, acc = weighted[-1], 0.0
        for a in weighted:
            acc += route.weights[a.profile.adapter_id]
            if point < acc:
                chosen = a
                break
        rest = [a for a in ranked if a is not chosen]
        return [chosen, *rest], "weight-based choice"
    if route.mode == "best_score":
        if rclass > RClass.R1:
            raise ValueError(f"best_score routing is not allowed for {rclass} capabilities (spec 9.3)")
        ranked = sorted(in_order(route.candidates), key=lambda a: selection_score(a, request, route.selection_weights, pool), reverse=True)
        return ranked, "highest selection score"
    raise ValueError(f"unknown routing mode {route.mode!r}")


# ---------------------------------------------------------------- portfolio


@dataclass(frozen=True)
class ConcentrationBreach:
    supplier_id: str
    share: float
    limit: float
    capabilities: tuple[str, ...]


def concentration(routes: Sequence[Route], adapters: Mapping[str, Adapter], limit: float) -> list[ConcentrationBreach]:
    """Suppliers that are primary for more than ``limit`` of critical routes, without an approved exception."""
    critical = [r for r in routes if r.critical]
    if not critical:
        return []
    primaries = {r.capability: adapters[r.primary_for()].profile.supplier_id for r in critical}
    counts = Counter(primaries.values())
    breaches = []
    for supplier, count in counts.items():
        share = count / len(critical)
        caps = tuple(sorted(c for c, s in primaries.items() if s == supplier))
        excepted = all(r.concentration_exception for r in critical if r.capability in caps)
        if share > limit and not excepted:
            breaches.append(ConcentrationBreach(supplier, share, limit, caps))
    return breaches

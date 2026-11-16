"""Request and response envelopes (spec section 7)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

ENVELOPE_VERSION = "0.1"
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")


def classification_rank(name: str) -> int:
    try:
        return CLASSIFICATIONS.index(name)
    except ValueError as exc:
        raise ValueError(f"unknown data classification: {name!r}") from exc


@dataclass
class Request:
    capability_id: str
    capability_version: str
    process_id: str
    step: str
    principal: str
    input: dict[str, Any]
    data_classification: str
    idempotency_key: str
    residency: tuple[str, ...] | None = None
    segment: str | None = None
    lease_expires_at: str | None = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self, *, values: bool = True) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "envelope_version": ENVELOPE_VERSION,
            "trace_id": self.trace_id,
            "idempotency_key": self.idempotency_key,
            "capability": {"id": self.capability_id, "version": self.capability_version},
            "process": {"id": self.process_id, "step": self.step},
            "principal": self.principal,
            "input": self.input if values else {k: "<withheld>" for k in self.input},
            "data_classification": self.data_classification,
        }
        if self.residency is not None:
            doc["residency"] = list(self.residency)
        if self.segment is not None:
            doc["segment"] = self.segment
        if self.lease_expires_at is not None:
            doc["lease_expires_at"] = self.lease_expires_at
        return doc


@dataclass
class Response:
    trace_id: str
    status: str  # ok | failed | rejected | escalated
    rclass: str
    route_mode: str
    route_reason: str
    latency_ms: float
    output: dict[str, Any] | None = None
    evidence: list[dict[str, str]] = field(default_factory=list)
    confidence: float | None = None
    cost: dict[str, Any] | None = None
    supplier_id: str | None = None
    adapter_version: str | None = None
    error: str | None = None
    # "unknown" when a supplier may have acted but the call could not be confirmed (issue #27);
    # ``supplier_id`` then names the supplier to reconcile with.
    outcome: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "envelope_version": ENVELOPE_VERSION,
            "trace_id": self.trace_id,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 3),
            "rclass": self.rclass,
            "route": {"mode": self.route_mode, "reason": self.route_reason},
        }
        if self.output is not None:
            doc["output"] = self.output
        if self.evidence:
            doc["evidence"] = self.evidence
        if self.confidence is not None:
            doc["confidence"] = self.confidence
        if self.cost is not None:
            doc["cost"] = self.cost
        if self.supplier_id is not None:
            doc["supplier"] = {"id": self.supplier_id, "adapter_version": self.adapter_version or "unknown"}
        if self.error is not None:
            doc["error"] = self.error
        if self.outcome is not None:
            doc["outcome"] = self.outcome
        return doc

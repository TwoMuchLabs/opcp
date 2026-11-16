"""Adapters and supplier profiles (spec section 8)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping

from .envelope import Request
from .rclass import RClass


@dataclass(frozen=True)
class SupplierProfile:
    """What the business knows and has approved about one supplier for one capability."""

    adapter_id: str
    supplier_id: str
    kind: str  # vendor | internal | human
    capability: str
    contract_major: int
    adapter_version: str = "0.1.0"
    register_ref: str | None = None  # third-party register entry, for external suppliers
    approved: bool = False
    contract_end: dt.date | None = None
    max_data_classification: str = "internal"
    regions: frozenset[str] = frozenset()
    max_rclass: RClass = RClass.R0
    conformance_passed: bool = False
    retains_input: bool = False
    quality: Mapping[str, float] = field(default_factory=dict)  # segment -> score 0..1, "default" key
    cost_per_call: float = 0.0
    currency: str = "SGD"
    latency_ms_p95: float = 1000.0

    def __post_init__(self) -> None:
        if self.kind not in ("vendor", "internal", "human"):
            raise ValueError(f"supplier kind must be vendor, internal or human, not {self.kind!r}")
        if self.kind == "vendor" and not self.register_ref:
            raise ValueError(f"external supplier {self.supplier_id!r} needs a third-party register reference")

    def quality_for(self, segment: str | None) -> float:
        if segment is not None and segment in self.quality:
            return self.quality[segment]
        return self.quality.get("default", 0.0)


class DefiniteFailure(Exception):
    """Raise from :meth:`Adapter.invoke` when the supplier certainly did not act.

    Examples: the supplier refused the request before doing anything, or the connection failed before
    the request was sent. Any other exception, a timeout included, leaves the outcome *unknown*: the
    supplier may have acted. For a capability with a lasting effect (Reversibility Class R2 or above, or
    the ``transact`` or ``notify`` archetype) the control plane then does not try another supplier, because
    that could repeat the effect (issue #27). For other capabilities both kinds of error fail over.
    """


@dataclass
class AdapterResult:
    output: dict[str, Any]
    evidence: list[dict[str, str]] = field(default_factory=list)
    confidence: float | None = None
    cost: float | None = None


class Adapter(ABC):
    """Connects one supplier to one capability contract.

    Subclasses implement :meth:`invoke`. The base class honours idempotency keys,
    so a repeated request returns the first result without repeating the effect.
    """

    def __init__(self, profile: SupplierProfile):
        self.profile = profile
        self._results: dict[str, AdapterResult] = {}
        self.invocations = 0  # how many times the supplier's effect actually ran

    def healthy(self) -> bool:
        return True

    @staticmethod
    def _key(payload: dict[str, Any], request: Request) -> str:
        body = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(f"{request.principal}\x1f{request.idempotency_key}\x1f{body}".encode()).hexdigest()

    def call(self, payload: dict[str, Any], request: Request) -> AdapterResult:
        """Invoke once per (principal, idempotency key, payload). A different payload is a different call."""
        key = self._key(payload, request)
        if key in self._results:
            return self._results[key]
        result = self.invoke(payload, request)
        self.invocations += 1
        self._results[key] = result
        return result

    def forget(self, payload: dict[str, Any], request: Request) -> None:
        """Drop a remembered result the runtime did not accept, so a retry reaches the supplier again."""
        self._results.pop(self._key(payload, request), None)

    @abstractmethod
    def invoke(self, payload: dict[str, Any], request: Request) -> AdapterResult:
        """Perform the capability. ``payload`` is already leased to the contract's declared fields."""

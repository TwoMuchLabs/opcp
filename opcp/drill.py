"""Summarise a shadow drill from the event log (spec 9.6).

A shadow route copies live requests to an alternative supplier and records how its output compares.
This module turns those ``shadow`` entries into figures for a swap drill: how often the alternative
agreed with the live supplier, field by field, how often it failed, and what it cost. Agreement is not
regression evidence by itself; the drill record (SWAP-DRILL section 5) judges both suppliers against the
business's expected outcomes.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass
class ShadowSummary:
    capability: str
    adapter: str
    compared: int = 0          # shadow calls that returned valid output
    full_agreement: int = 0    # of those, how many agreed on every compared field
    errors: int = 0
    invalid: int = 0
    skipped: Counter = field(default_factory=Counter)  # reason -> count
    field_agreement: dict[str, list[int]] = field(default_factory=dict)  # field -> [agreed, compared]
    latency_ms: list[float] = field(default_factory=list)
    cost: float = 0.0

    @property
    def attempted(self) -> int:
        return self.compared + self.errors + self.invalid

    @property
    def agreement_rate(self) -> float | None:
        return self.full_agreement / self.compared if self.compared else None

    def to_dict(self) -> dict[str, Any]:
        lat = sorted(self.latency_ms)
        return {
            "capability": self.capability,
            "adapter": self.adapter,
            "attempted": self.attempted,
            "compared": self.compared,
            "full_agreement": self.full_agreement,
            "agreement_rate": self.agreement_rate,
            "errors": self.errors,
            "invalid": self.invalid,
            "skipped": dict(self.skipped),
            "field_agreement": {f: a / n for f, (a, n) in sorted(self.field_agreement.items()) if n},
            "latency_ms_median": lat[len(lat) // 2] if lat else None,
            "cost": round(self.cost, 4),
        }


def summarise(entries: Iterable[Mapping[str, Any]]) -> list[ShadowSummary]:
    """One summary per (capability, shadow supplier), from event-log entries."""
    out: dict[tuple[str, str], ShadowSummary] = {}
    for e in entries:
        if e.get("kind") != "shadow":
            continue
        key = (e.get("capability", "?"), e.get("adapter", "?"))
        s = out.setdefault(key, ShadowSummary(*key))
        outcome = e.get("outcome")
        if outcome == "skipped":
            s.skipped[e.get("reason", "unspecified")] += 1
        elif outcome == "error":
            s.errors += 1
        elif outcome == "invalid":
            s.invalid += 1
        elif outcome == "ok":
            s.compared += 1
            agreed, disagreed = e.get("agreed", []), e.get("disagreed", [])
            if not disagreed:
                s.full_agreement += 1
            for f in agreed:
                s.field_agreement.setdefault(f, [0, 0])
                s.field_agreement[f][0] += 1
                s.field_agreement[f][1] += 1
            for f in disagreed:
                s.field_agreement.setdefault(f, [0, 0])
                s.field_agreement[f][1] += 1
            if e.get("latency_ms") is not None:
                s.latency_ms.append(float(e["latency_ms"]))
            if e.get("cost") is not None:
                s.cost += float(e["cost"])
    return list(out.values())


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def render_text(summaries: list[ShadowSummary]) -> str:
    if not summaries:
        return "No shadow entries found. Add a `shadow` block to a route (spec 9.6) and run traffic through it.\n"
    lines: list[str] = []
    for s in summaries:
        d = s.to_dict()
        lines.append(f"{s.capability}: shadow supplier {s.adapter}")
        rate = "n/a" if d["agreement_rate"] is None else f"{d['agreement_rate']:.1%}"
        lines.append(f"  compared {s.compared} of {s.attempted} attempted; full agreement {s.full_agreement} ({rate})")
        lines.append(f"  errors {s.errors}, invalid output {s.invalid}")
        for f, r in d["field_agreement"].items():
            lines.append(f"  field {f}: {r:.1%} agreement")
        if d["latency_ms_median"] is not None:
            lines.append(f"  median shadow latency {d['latency_ms_median']:.0f} ms; shadow cost {d['cost']}")
        for reason, n in sorted(s.skipped.items()):
            lines.append(f"  skipped {n}: {reason}")
        lines.append("")
    lines.append("Agreement with the live supplier is not regression evidence on its own: a swap drill judges the "
                 "candidate against the business's own expected outcomes (SWAP-DRILL section 5), and the live "
                 "supplier can be wrong. Use these figures as input to a drill record and check it with "
                 "`opcp swap-drill`. See docs/SWAP-DRILL.md.")
    return "\n".join(lines) + "\n"


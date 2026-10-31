"""Stable service boundary for OPCP swap-drill evidence evaluation.

Soven and other control planes should depend on this small boundary rather
than importing evaluator implementation details. OPCP remains the authority
for validation and promotion semantics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .swap_drill import evaluate_evidence, load_swap_evidence


def evaluate_swap_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate an already-loaded OPCP v0.3 evidence record."""
    return evaluate_evidence(evidence)


def evaluate_swap_evidence_file(path: str | Path) -> dict[str, Any]:
    """Evaluate evidence from a JSON file through the same boundary."""
    return evaluate_evidence(load_swap_evidence(path))

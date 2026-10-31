"""Stable application boundary for OPCP swap-drill evaluation.

The runtime boundary deliberately returns plain JSON-compatible data. An HTTP
service, job runner, or Soven server adapter can wrap this function without
coupling itself to OPCP's internal evaluator objects.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .swap_drill import evaluate_evidence, load_swap_evidence


def evaluate_swap_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one in-memory OPCP v0.3 evidence record."""
    return evaluate_evidence(evidence)


def evaluate_swap_evidence_file(path: str | Path) -> dict[str, Any]:
    """Evaluate one evidence file through the same runtime boundary as a service."""
    return evaluate_swap_evidence(load_swap_evidence(path))

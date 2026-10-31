"""Stable service boundary for OPCP swap-drill evidence evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .swap_drill import run_swap_drill


def evaluate_swap_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Evaluate loaded OPCP v0.3 evidence without exposing evaluator internals."""
    with NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8") as handle:
        json.dump(evidence, handle)
        handle.flush()
        return run_swap_drill(Path(handle.name))


def evaluate_swap_evidence_file(path: str | Path) -> dict[str, Any]:
    """Evaluate evidence from a JSON file through the same boundary."""
    return run_swap_drill(Path(path))

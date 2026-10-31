"""Stable service boundary for OPCP swap-drill evaluation.

Soven and other control planes should call this module rather than importing
swap-drill implementation details. The boundary is transport-neutral: callers
may expose it through HTTP, a job worker, or an in-process adapter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .swap_drill import run_swap_drill


def evaluate_swap_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Evaluate an already-loaded OPCP v0.3 evidence record.

    The evaluator remains the single owner of promotion semantics. This
    function only establishes the stable integration boundary and returns a
    JSON-compatible result.
    """
    import json
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8") as handle:
        json.dump(evidence, handle)
        handle.flush()
        return run_swap_drill(Path(handle.name))


def evaluate_swap_evidence_file(path: str | Path) -> dict[str, Any]:
    """Evaluate evidence from a JSON file using the same service boundary."""
    return run_swap_drill(Path(path))

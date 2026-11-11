"""Small CLI boundary for running OPCP v0.3 swap-drill evidence.

This is intentionally a thin adapter over ``opcp.swap_drill`` so any control
plane can invoke the same deterministic evaluator from a local
process without importing private implementation details.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .swap_drill import run_swap_drill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate OPCP v0.3 swap-drill evidence")
    parser.add_argument("evidence", type=Path, help="Path to a JSON swap-drill evidence record")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the result")
    args = parser.parse_args(argv)

    result = run_swap_drill(args.evidence)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["promotion_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

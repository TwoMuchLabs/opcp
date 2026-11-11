"""Append-only event log: the business's record of every request, decision and response (spec 11.1).

Optional tamper evidence (``chain=True``, proposed for the specification in issue #33): every entry
carries ``prev_hash``, the SHA-256 of the previous line's exact bytes as written (the first entry uses
``GENESIS``). Editing, inserting, deleting or reordering any entry breaks the chain, and
:func:`verify_chain` finds where. Removing entries from the *end* cannot be detected from the file
alone, so a deployment that needs that keeps the head hash (:meth:`EventLog.head`) somewhere else, such
as a register, a timestamping service or a separate store, and passes it to the check.

Hashing the exact bytes of each line means a verifier needs no canonical JSON form; it only needs the
file exactly as exported.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

GENESIS = "0" * 64


def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


class EventLog:
    """Entries are serialised on write, so later changes to the caller's objects cannot alter history."""

    def __init__(self, path: str | Path | None = None, *, chain: bool = False):
        self.path = Path(path) if path else None
        self.chain = chain
        self._lines: list[str] = []

    def append(self, kind: str, trace_id: str, **data: Any) -> None:
        entry = {"at": dt.datetime.now(dt.timezone.utc).isoformat(), "kind": kind, "trace_id": trace_id, **data}
        if self.chain:
            entry["prev_hash"] = self.head()
        line = json.dumps(entry, sort_keys=True, default=str)
        self._lines.append(line)
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def head(self) -> str:
        """Hash of the last entry written, or ``GENESIS`` for an empty log. Keep it to detect truncation."""
        return line_hash(self._lines[-1]) if self._lines else GENESIS

    def entries(self, trace_id: str | None = None) -> list[dict[str, Any]]:
        items = (json.loads(line) for line in self._lines)
        return [e for e in items if trace_id is None or e["trace_id"] == trace_id]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.entries())

    def __len__(self) -> int:
        return len(self._lines)

    def export_jsonl(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text("".join(line + "\n" for line in self._lines), encoding="utf-8")
        return path


@dataclass(frozen=True)
class ChainCheck:
    ok: bool
    entries: int
    head: str
    problem: str | None = None
    line: int | None = None  # 1-based line number of the first problem


def verify_chain(lines: Iterable[str], expected_head: str | None = None) -> ChainCheck:
    """Check a hash-chained log, line by line, exactly as exported (one JSON entry per line)."""
    previous, count = GENESIS, 0
    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if not line.strip():
            return ChainCheck(False, count, previous, "blank line inside the log", number)
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return ChainCheck(False, count, previous, "not a JSON entry", number)
        if not isinstance(entry, dict) or "prev_hash" not in entry:
            return ChainCheck(False, count, previous, "entry has no prev_hash; the log is not chained", number)
        if entry["prev_hash"] != previous:
            return ChainCheck(False, count, previous,
                              "prev_hash does not match the previous entry: an entry was changed, inserted, removed or moved",
                              number)
        previous, count = line_hash(line), count + 1
    if expected_head is not None and previous != expected_head:
        return ChainCheck(False, count, previous, "the log does not end at the expected head: entries are missing from the end")
    return ChainCheck(True, count, previous)


def verify_file(path: str | Path, expected_head: str | None = None) -> ChainCheck:
    with Path(path).open(encoding="utf-8") as handle:
        return verify_chain(handle, expected_head)

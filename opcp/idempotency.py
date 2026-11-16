"""Where the control plane keeps its idempotency records (spec 7.1, 9.5; issue #31).

Two kinds of record, both keyed by (capability, principal, idempotency key):

- **completed**: the input fingerprint and the response, so a repeat replays the response instead of
  repeating the effect;
- **unresolved**: the input fingerprint and the supplier that may have acted, so a retry after an unknown
  outcome goes back to that supplier and no other.

:class:`IdempotencyStore` keeps both in memory, as the control plane always has: a restart forgets them.
:class:`FileIdempotencyStore` also writes every change to a JSON Lines file, flushed to disk before the
call goes on, and reads it back on start. With it, a restart or a crash cannot make the control plane
repeat an effect:

- the control plane writes an *unresolved* record before it calls a supplier of a capability with a
  lasting effect, and replaces it once the outcome is known;
- if the process dies in between, the record survives, and a retry with the same key goes to that
  supplier only (whose own idempotency, spec 8.3, settles it).

The file holds responses, including output values such as receipts or extracted fields, so it needs the
same protection as the event log with values. It is created readable by its owner only. Completed records
older than ``retention`` are dropped; unresolved records are never dropped automatically, because
forgetting one could repeat an effect. One process writes one file; instances that share keys need a
shared store, such as a database, implementing the same two mappings.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Callable, Iterator

from .envelope import Response

Key = tuple[str, str, str]


class IdempotencyStore:
    """In-memory records (the default): ``completed`` and ``unresolved`` mappings keyed by ``Key``."""

    def __init__(self) -> None:
        self.completed: MutableMapping[Key, tuple[str, Response]] = {}
        self.unresolved: MutableMapping[Key, tuple[str, str, str]] = {}


class FileIdempotencyStore(IdempotencyStore):
    """Idempotency records that survive a restart: every change is appended to ``path`` and synced to disk.

    ``retention`` is how long a completed response stays replayable. ``None`` keeps it until the file is
    removed; a deployment should set the window its retry policy needs (issue #31 proposes making a
    minimum part of the specification).
    """

    def __init__(self, path: str | Path, *, retention: dt.timedelta | None = None, sync: bool = True,
                 clock: Callable[[], dt.datetime] | None = None):
        super().__init__()
        self.path = Path(path)
        self.retention = retention
        self.sync = sync
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._lock = threading.Lock()
        self._written: dict[tuple[str, Key], str] = {}  # when each live record was written
        completed: dict[Key, tuple[str, Response]] = {}
        unresolved: dict[Key, tuple[str, str, str]] = {}
        self.skipped_lines = self._load(completed, unresolved)
        self.completed = _Persisted(self, "completed", completed)
        self.unresolved = _Persisted(self, "unresolved", unresolved)
        self.compact()

    # ------------------------------------------------------------ file

    def _load(self, completed: dict, unresolved: dict) -> int:
        """Rebuild state from the file; the last write for a key wins. Returns lines that could not be read."""
        if not self.path.exists():
            return 0
        skipped = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                key = tuple(entry["key"])
                target = completed if entry["map"] == "completed" else unresolved
                if entry["op"] == "del":
                    target.pop(key, None)
                    self._written.pop((entry["map"], key), None)
                    continue
                if entry["map"] == "completed":
                    target[key] = (entry["value"]["fingerprint"], Response.from_dict(entry["value"]["response"]))
                else:
                    target[key] = tuple(entry["value"])
                self._written[(entry["map"], key)] = entry["at"]
            except (ValueError, KeyError, TypeError):
                skipped += 1  # a line cut short by a crash mid-write: nothing after it depended on it
        for key in [k for k in completed if self._expired("completed", k)]:
            del completed[key]
            self._written.pop(("completed", key), None)
        return skipped

    def _expired(self, kind: str, key: Key) -> bool:
        if kind != "completed" or self.retention is None:
            return False
        at = self._written.get((kind, key))
        return at is not None and dt.datetime.fromisoformat(at) < self._clock() - self.retention

    def _append(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, sort_keys=True, default=str) + "\n"
        with self._lock:
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                if self.sync:
                    os.fsync(fh.fileno())

    def record(self, kind: str, key: Key, value: Any | None) -> None:
        at = self._clock().isoformat()
        if value is None:
            self._append({"at": at, "op": "del", "map": kind, "key": list(key)})
            self._written.pop((kind, key), None)
            return
        if kind == "completed":
            fingerprint, response = value
            value = {"fingerprint": fingerprint, "response": response.to_dict()}
        self._append({"at": at, "op": "put", "map": kind, "key": list(key), "value": value})
        self._written[(kind, key)] = at

    def compact(self) -> None:
        """Rewrite the file with only live records, atomically, dropping expired and superseded lines."""
        tmp = self.path.with_name(self.path.name + ".tmp")
        with self._lock:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for kind, mapping in (("completed", self.completed), ("unresolved", self.unresolved)):
                    for key, value in mapping._data.items():
                        if kind == "completed":
                            value = {"fingerprint": value[0], "response": value[1].to_dict()}
                        at = self._written.get((kind, key)) or self._clock().isoformat()
                        fh.write(json.dumps({"at": at, "op": "put", "map": kind, "key": list(key), "value": value},
                                            sort_keys=True, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)


class _Persisted(MutableMapping):
    """A dict that writes every change through to its store before returning."""

    def __init__(self, store: FileIdempotencyStore, kind: str, data: dict):
        self._store, self._kind, self._data = store, kind, data

    def _drop_if_expired(self, key: Any) -> None:
        if key in self._data and self._store._expired(self._kind, key):
            self._store.record(self._kind, key, None)
            del self._data[key]

    def __getitem__(self, key: Key) -> Any:
        self._drop_if_expired(key)
        return self._data[key]

    def __setitem__(self, key: Key, value: Any) -> None:
        self._store.record(self._kind, key, value)  # on disk first, then in memory
        self._data[key] = value

    def __delitem__(self, key: Key) -> None:
        if key not in self._data:
            raise KeyError(key)
        self._store.record(self._kind, key, None)
        del self._data[key]

    def __contains__(self, key: object) -> bool:
        self._drop_if_expired(key)
        return key in self._data

    def __iter__(self) -> Iterator[Key]:
        return iter(list(self._data))

    def __len__(self) -> int:
        return len(self._data)

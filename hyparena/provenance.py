"""Append-only log of every LLM call and notable events (JSON lines)."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class ProvenanceLog:
    """Writes to a JSONL file when `path` is given; always keeps the entries in memory."""

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path else None
        self.entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def write(self, entry: dict[str, Any]) -> None:
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
        with self._lock:
            self.entries.append(entry)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

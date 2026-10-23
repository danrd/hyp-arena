"""Literature search interface. Every connector returns Evidence records (hyparena.state.Evidence).

`as_of` (ISO date) restricts results to what was published on or before that date; backtests need it
so that later findings do not leak into the evaluation."""
from __future__ import annotations

from typing import Optional, Protocol

from hyparena.state import Evidence


class SearchTool(Protocol):
    def search(self, query: str, limit: int = 5, as_of: Optional[str] = None) -> list[Evidence]: ...


class NullSearch:
    def search(self, query: str, limit: int = 5, as_of: Optional[str] = None) -> list[Evidence]:
        return []


class MultiSearch:
    """Several connectors queried in turn; results merged, deduplicated by (source, record_id)."""

    def __init__(self, *tools: SearchTool):
        self.tools = tools

    def search(self, query: str, limit: int = 5, as_of: Optional[str] = None) -> list[Evidence]:
        """Runs tools and merges results. A final guard drops records whose date is after `as_of`
        or missing, so that connector or server changes do not leak future knowledge."""
        seen, out = set(), []
        for tool in self.tools:
            for ev in tool.search(query, limit, as_of):
                if as_of:
                    # Pad date to compare ISO strings safely: YYYY -> YYYY-01-01, YYYY-MM -> YYYY-MM-01
                    pd = ev.publication_date or ""
                    if len(pd) == 4:
                        pd += "-01-01"
                    elif len(pd) == 7:
                        pd += "-01"
                    if not pd or pd > as_of:
                        continue

                key = (ev.source, ev.record_id)
                if key not in seen:
                    seen.add(key)
                    out.append(ev)
        return out[:limit * len(self.tools)]

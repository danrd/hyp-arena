"""Europe PMC connector (REST search, no key needed). Abstract excerpts as evidence text.

Endpoint: https://www.ebi.ac.uk/europepmc/webservices/rest/search (resultType=core gives abstracts,
first publication dates and licences). `as_of` adds a FIRST_PDATE range to the query. Rate limits were
not read from the official documentation; requests are sequential per call, retried on errors, and
cached in memory for the run."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from hyparena.state import Evidence

URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

#: Evidence tiers (docs/architecture.md): 2 peer-reviewed text, 4 preprint.
PREPRINT_SOURCES = {"PPR"}


class EuropePMCSearch:
    def __init__(self, timeout: float = 30.0, retries: int = 2, excerpt_chars: int = 800,
                 client: Optional[httpx.Client] = None):
        self.timeout, self.retries, self.excerpt_chars = timeout, retries, excerpt_chars
        self._client = client or httpx.Client(timeout=timeout)
        self._cache: dict[tuple, list[Evidence]] = {}
        self._lock = threading.Lock()
        self.last_error = ""

    def _query(self, query: str, as_of: Optional[str]) -> str:
        q = f"({query})"
        if as_of:
            q += f" AND FIRST_PDATE:[1800-01-01 TO {as_of}]"
        return q

    def search(self, query: str, limit: int = 5, as_of: Optional[str] = None) -> list[Evidence]:
        key = (query, limit, as_of)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        params = {"query": self._query(query, as_of), "format": "json", "resultType": "core",
                  "pageSize": str(limit)}
        data = None
        for attempt in range(self.retries + 1):
            try:
                r = self._client.get(URL, params=params)
                r.raise_for_status()
                data = r.json()
                break
            except (httpx.HTTPError, ValueError) as e:
                self.last_error = f"{type(e).__name__}: {e}"
                time.sleep(2 * (attempt + 1))
        if data is None:
            return []
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out = [self._record(item, query, now) for item in data.get("resultList", {}).get("result", [])]
        with self._lock:
            self._cache[key] = out
        return out

    def _record(self, item: dict, query: str, now: str) -> Evidence:
        src, rid = item.get("source", ""), item.get("id", "")
        types = item.get("pubTypeList", {}).get("pubType", [])
        abstract = (item.get("abstractText") or "").replace("<h4>", "").replace("</h4>", " ")
        return Evidence(
            source="europepmc", record_id=f"{src}:{rid}", title=item.get("title", ""),
            text=abstract[: self.excerpt_chars], url=f"https://europepmc.org/article/{src}/{rid}",
            publication_date=item.get("firstPublicationDate"), retrieved_at=now, query=query,
            tier=4 if src in PREPRINT_SOURCES else 2,
            study_type="; ".join(types) if isinstance(types, list) else str(types),
            license=item.get("license", "") or "",
            extra={k: item[k] for k in ("pmid", "pmcid", "doi", "journalTitle", "isOpenAccess", "citedByCount")
                   if k in item})

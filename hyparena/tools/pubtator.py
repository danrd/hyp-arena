"""PubTator3 connector: articles with normalized entities (genes, chemicals, diseases, ...).

Search API: https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/?text=... (no key; usage terms and
limits not confirmed). Results carry title, date, DOI, PMID and a highlighted snippet with entity tags
such as `@CHEMICAL_MESH:D020123`, which become `entity_ids`.

Not usable for backtests: the search favours recent papers and I found no server-side date filter; in a
check (2026-10-14), the first 50 results for "rapamycin lifespan mice" were all after 2015. So under
`as_of` this connector returns nothing instead of spending requests; use Europe PMC for dated retrieval."""
from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Optional

from hyparena.state import Evidence
from hyparena.tools.http import Http

URL = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/"
TAG = re.compile(r"@([A-Z]+)_([A-Za-z]+:[^\s@]+)")
NOISE = re.compile(r"@[A-Z]+_\S+|@@@|</?m>")


class PubTatorSearch:
    def __init__(self, http: Optional[Http] = None, pages: int = 1):
        self.http, self.pages = http or Http(), pages
        self._cache: dict[tuple, list[Evidence]] = {}
        self._lock = threading.Lock()

    def search(self, query: str, limit: int = 5, as_of: Optional[str] = None) -> list[Evidence]:
        if as_of:
            return []
        key = (query, limit)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out: list[Evidence] = []
        for page in range(1, self.pages + 1):
            data = self.http.get_json(URL, {"text": query, "page": page})
            if not data:
                break
            for r in data.get("results", []):
                date = (r.get("date") or "")[:10] or None
                hl = r.get("text_hl", "") or ""
                out.append(Evidence(
                    source="pubtator", record_id=f"PMID:{r.get('pmid')}", title=r.get("title", ""),
                    text=re.sub(r"\s+", " ", NOISE.sub("", hl)).strip(),
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{r.get('pmid')}/", publication_date=date,
                    retrieved_at=now, query=query, tier=2,
                    # the excerpt is the paper's own text; the entity tags on it are machine-derived
                    epistemic_type="primary_text",
                    entity_ids=sorted({f"{t}:{i}" for t, i in TAG.findall(hl)}),
                    extra={k: r[k] for k in ("pmid", "doi", "journal", "citations") if r.get(k)}))
        out = out[:limit]
        with self._lock:
            self._cache[key] = out
        return out

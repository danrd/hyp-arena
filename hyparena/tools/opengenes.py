"""Open Genes connector (a curated database of ageing-related genes; API without key).

Looks up gene symbols found in the query (upper-case tokens such as MTOR, FOXO3) at
https://open-genes.com/api/gene/{symbol}. Evidence tier 1 (curated with explicit criteria). The record
has no per-entry publication date, so under `as_of` (backtests) this connector returns nothing rather
than risk later knowledge. Open Genes' authors note that inclusion is not proof of a human longevity link."""
from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Optional

from hyparena.state import Evidence
from hyparena.tools.http import Http

URL = "https://open-genes.com/api/gene/{}"
SYMBOL = re.compile(r"\b[A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]+)?\b")
STOP = {"DNA", "RNA", "ROS", "AND", "OR", "NOT", "THE", "AMPK", "ATP", "NAD", "SASP", "ITP", "ISR", "ER", "UPR"}


class OpenGenesSearch:
    def __init__(self, http: Optional[Http] = None):
        self.http = http or Http()
        self._cache: dict[str, Optional[Evidence]] = {}
        self._lock = threading.Lock()

    def symbols(self, query: str) -> list[str]:
        return [s for s in dict.fromkeys(SYMBOL.findall(query)) if s not in STOP]

    def gene(self, symbol: str) -> Optional[Evidence]:
        with self._lock:
            if symbol in self._cache:
                return self._cache[symbol]
        g = self.http.get_json(URL.format(symbol), ok_404=True)
        ev = None
        if isinstance(g, dict) and g.get("symbol"):
            res = g.get("researches") or {}
            lifespan = res.get("increaseLifespan") or []
            organisms = sorted({r.get("modelOrganism") for r in lifespan if r.get("modelOrganism")})
            mechanisms = [m.get("name") for m in g.get("agingMechanisms") or []][:8]
            causes = [c.get("name") for c in g.get("commentCause") or []][:5]
            text = (f"Confidence level: {(g.get('confidenceLevel') or {}).get('name', 'unknown')}. "
                    f"Ageing mechanisms: {', '.join(mechanisms) or 'none listed'}. "
                    f"Selection criteria: {'; '.join(causes) or 'none listed'}. "
                    f"Lifespan-change studies: {len(lifespan)} ({', '.join(organisms) or 'no organism listed'}); "
                    f"other evidence groups: " + ", ".join(f"{k} {len(v)}" for k, v in res.items() if v and k != "increaseLifespan"))
            ev = Evidence(source="opengenes", record_id=f"OG:{g['symbol']}", title=f"Open Genes: {g['symbol']} ({g.get('name', '')})",
                          text=text, url=f"https://open-genes.com/genes/{g['symbol']}",
                          retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), tier=1,
                          study_type="curated database", epistemic_type="curated_record", entity_ids=[f"HGNC:{g['symbol']}"],
                          extra={"lifespan_pmids": [r.get("pmid") for r in lifespan if r.get("pmid")][:20]})
        with self._lock:
            self._cache[symbol] = ev
        return ev

    def search(self, query: str, limit: int = 5, as_of: Optional[str] = None) -> list[Evidence]:
        if as_of:
            return []
        found = [self.gene(s) for s in self.symbols(query)[:limit]]
        return [e for e in found if e is not None]

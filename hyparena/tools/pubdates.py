"""First public date of PubMed papers (NCBI E-utilities), cached: the date cut of every run at a date T rests on it."""
from __future__ import annotations

import json
from pathlib import Path

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


DATES_CACHE = Path("data/cache/pubdates.json")      # found dates only: a paper never gets an earlier first date


def _pubmed_date(text: str) -> str | None:
    """ISO date from a PubMed date string ("2016 Nov 14", "2016 Dec", "2016/11/15 06:00"); a missing day or
    month counts as the first."""
    parts = text.replace("/", " ").replace("-", " ").split()
    if not parts or not parts[0].isdigit() or len(parts[0]) != 4:
        return None
    month, day = 1, 1
    if len(parts) > 1:
        month = int(parts[1]) if parts[1].isdigit() else _MONTHS.get(parts[1][:3].lower(), 1)
    if len(parts) > 2 and parts[2].isdigit():
        day = int(parts[2])
    return f"{parts[0]}-{month:02d}-{day:02d}"


def pubdates(pmids: list[str]) -> dict[str, str]:
    """PubMed id -> ISO date of first public appearance, via NCBI E-utilities (batches of 150): the earliest
    of the electronic, print and PubMed-entry dates. (The print date alone can come weeks after the paper
    was online, which let a backtest's evidence cut-off include the paper itself.)"""
    from hyparena.tools import pubmed                # shares PubMed's rate limit with the verifier's threads
    try:
        cache = json.loads(DATES_CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    dates = {p: cache[p] for p in pmids if p in cache}
    todo = [p for p in pmids if p not in dates]
    for i in range(0, len(todo), 150):
        batch = todo[i:i + 150]
        r = pubmed._get("esummary.fcgi", {"db": "pubmed", "id": ",".join(batch), "retmode": "json"})
        res = r.json().get("result", {})
        for p in batch:
            rec = res.get(p) or {}
            found = [_pubmed_date(rec.get(k) or "") for k in ("epubdate", "pubdate", "sortpubdate")]
            found += [_pubmed_date(h.get("date", "")) for h in rec.get("history") or []
                      if h.get("pubstatus") in ("entrez", "pubmed", "aheadofprint")]
            found = [d for d in found if d]
            if found:
                dates[p] = min(found)
                cache[p] = dates[p]
    if todo:
        DATES_CACHE.parent.mkdir(parents=True, exist_ok=True)
        DATES_CACHE.write_text(json.dumps(cache, sort_keys=True))
    return dates

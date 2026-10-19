"""PubMed via NCBI E-utilities: search (optionally as of a date) and fetch of full abstracts, which the verifier
needs to check that every quote is verbatim. Cached in memory and in data/cache/pubmed (gitignored).
Without an API key NCBI allows about 3 requests per second; calls are spaced accordingly."""
from __future__ import annotations

import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import httpx

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "pubmed"
_lock = threading.Lock()
_last = [0.0]


def _get(path: str, params: dict) -> httpx.Response:
    with _lock:                                   # ≤ 3 requests per second, across threads
        wait = 0.35 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    for attempt in range(3):
        try:
            r = httpx.get(f"{BASE}/{path}", params=params, timeout=40)
            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except httpx.HTTPError:
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("PubMed request failed")


def search(query: str, retmax: int = 8, as_of: Optional[str] = None) -> list[str]:
    """PMIDs by relevance; with `as_of`, only records published on or before that date."""
    params = {"db": "pubmed", "term": query, "retmax": retmax, "sort": "relevance", "retmode": "json"}
    if as_of:
        params.update({"datetype": "pdat", "mindate": "1800/01/01", "maxdate": as_of.replace("-", "/")})
    return _get("esearch.fcgi", params).json().get("esearchresult", {}).get("idlist", [])


def fetch(pmids: list[str]) -> dict[str, dict]:
    """PMID → {pmid, title, abstract, year, date, pubtypes, first_author, journal}; cached."""
    out, todo = {}, []
    CACHE.mkdir(parents=True, exist_ok=True)
    for p in pmids:
        f = CACHE / f"{p}.json"
        if f.exists():
            out[p] = json.loads(f.read_text())
        else:
            todo.append(p)
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        root = ET.fromstring(_get("efetch.fcgi", {"db": "pubmed", "id": ",".join(batch), "retmode": "xml"}).content)
        for art in root.iter("PubmedArticle"):
            pmid = art.findtext(".//MedlineCitation/PMID") or ""
            parts = []
            for t in art.iterfind(".//Abstract/AbstractText"):
                text = "".join(t.itertext()).strip()
                label = t.get("Label")
                parts.append(f"{label}: {text}" if label and label.upper() not in text.upper()[:len(label) + 2] else text)
            year = art.findtext(".//Article/Journal/JournalIssue/PubDate/Year") or \
                (art.findtext(".//Article/Journal/JournalIssue/PubDate/MedlineDate") or "")[:4]
            rec = {"pmid": pmid, "title": "".join(art.find(".//ArticleTitle").itertext()).strip()
                   if art.find(".//ArticleTitle") is not None else "",
                   "abstract": " ".join(parts), "year": year,
                   "pubtypes": [p.text for p in art.iterfind(".//PublicationType") if p.text],
                   "first_author": art.findtext(".//AuthorList/Author/LastName") or "",
                   "journal": art.findtext(".//Journal/Title") or ""}
            out[pmid] = rec
            (CACHE / f"{pmid}.json").write_text(json.dumps(rec, ensure_ascii=False))
    return out


def is_review(rec: dict) -> bool:
    return any(re.search(r"review|meta-analysis", t, re.I) for t in rec.get("pubtypes", []))

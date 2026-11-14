"""MeSH descriptors for the card's entities, found by code through NCBI E-utilities (no model): an exact match of the
descriptor or of one of its entry terms, else nothing (no guessing). Cached on disk (data/cache/mesh.json), "not found"
included; network errors are not cached.

    lookup("squat exercise")      -> None (no exact descriptor or entry term)
    lookup("sarcopenia")          -> {"ui": "D055948", "name": "Sarcopenia", "trees": ["C05.651.534.500", ...],
                                      "entry_terms": ["Sarcopenia", ...]}
    topic("sarcopenia")           -> the same, only for diseases (C), phenomena and processes (G) or behaviour (F)
    synonyms("resistance training") -> the descriptor's entry terms ("Strength Training", "Weight-Lifting Exercise Program", ...)

Used for search synonyms (the queries missed half of the gold papers on wording), the topic of a hypothesis, and the
graph. docs/system/card.md, section 3.3 (identifiers).
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "mesh.json"
EU = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
_lock = threading.Lock()
_last = [0.0]
_cache: Optional[dict] = None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _get(path: str, params: dict) -> Optional[dict]:
    for attempt in range(3):
        with _lock:
            wait = 0.36 - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            return json.loads(urllib.request.urlopen(EU + path + "?" + urllib.parse.urlencode(params), timeout=30).read())
        except Exception:                                   # noqa: BLE001 - a network failure is not cached
            time.sleep(1 + attempt)
    return None


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    return _cache


def _save() -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(_load(), ensure_ascii=False))


def _summary(uid: str) -> Optional[dict]:
    r = _get("esummary.fcgi", {"db": "mesh", "id": uid, "retmode": "json"})
    if not r:
        return None
    d = (r.get("result") or {}).get(uid) or {}
    ui = d.get("ds_meshui", "")
    if not ui.startswith("D"):                              # descriptors only (not supplementary concepts or qualifiers)
        return {}
    terms = d.get("ds_meshterms") or []
    return {"ui": ui, "name": terms[0] if terms else "", "trees": [x.get("treenum", "") for x in d.get("ds_idxlinks") or []
                                                                   if x.get("treenum")],
            "entry_terms": terms}


def lookup(term: str) -> Optional[dict]:
    """The descriptor whose name or entry term equals `term` (case and punctuation aside); None when there is none."""
    key = _norm(term)
    if not key or key == "unknown" or len(key) < 3:
        return None
    cache = _load()
    if key in cache:
        return cache[key] or None
    found = {}
    for q, n in ((f'"{term}"[mh]', 5), (f'"{term}"', 20)):    # the heading / entry-term field first, then all fields
        r = _get("esearch.fcgi", {"db": "mesh", "term": q, "retmax": n, "retmode": "json"})
        if r is None:
            return None                                     # network error: not cached
        for uid in (r.get("esearchresult") or {}).get("idlist", []):
            d = _summary(uid)
            if d is None:
                return None
            if d and any(_norm(t) == key for t in d["entry_terms"]):
                found = d
                break
        if found:
            break
    cache[key] = found
    _save()
    return found or None


def topic(term: str) -> Optional[dict]:
    """A descriptor for the topic of a hypothesis: diseases (C), phenomena and processes (G), behaviour (F)."""
    d = lookup(term)
    return d if d and any(t[:1] in ("C", "G", "F") for t in d["trees"]) else None


def synonyms(term: str, n: int = 6) -> list[str]:
    """Short entry terms of the descriptor (the heading first), for a search block; [] when there is no exact descriptor."""
    d = lookup(term)
    if not d:
        return []
    out = [t for t in d["entry_terms"] if len(t.split()) <= 4 and "," not in t]
    return list(dict.fromkeys([d["name"]] + out))[:n]

"""ClinicalTrials.gov (API v2): the start date of the earliest registered trial with an intervention, for
`path_to_human` as of a date T (card spec 8a: a clinical-stage compound has a trial started before T).
The search is ClinicalTrials.gov's own intervention search (`query.intr`, which also matches synonyms), so it
can over-match a name that is part of another drug's name; the date is a baseline, not a curated fact.
Results, including "no trial", are cached on disk (data/cache/trials.json); network errors are not cached."""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "trials.json"
API = "https://clinicaltrials.gov/api/v2/studies"

_lock = threading.Lock()
_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    return _cache


def _fetch(name: str) -> Optional[str]:
    """Earliest start date (YYYY-MM or YYYY-MM-DD) of a trial naming the intervention, or "" for none;
    None on network trouble."""
    url = f"{API}?query.intr={urllib.parse.quote(name)}&sort=StartDate:asc&fields=NCTId,StartDate&pageSize=1"
    for attempt in range(4):
        try:
            r = httpx.get(url, timeout=30)
        except httpx.HTTPError:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            studies = r.json().get("studies") or []
            date = ((studies[0].get("protocolSection") or {}).get("statusModule") or {}).get("startDateStruct", {}).get("date") \
                if studies else ""
            return date or ""
        time.sleep(2 ** attempt)
    return None


def first_trial_start(name: str) -> Optional[str]:
    """Cached earliest trial start for a name; "" when no trial is registered, None when unknown (network)."""
    k = name.strip().lower()
    if not k:
        return None
    with _lock:
        if k in _load():
            return _load()[k]
    date = _fetch(name)
    if date is None:
        return None
    with _lock:
        _load()[k] = date
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_cache, ensure_ascii=False, indent=0))
    return date

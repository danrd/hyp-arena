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


RECORDS = ROOT / "data" / "cache" / "trial_records.json"
_records: Optional[dict] = None


def _record_text(study: dict) -> str:
    """The registry text a verifier quotes from: title, primary outcomes as registered, and the posted results
    of the primary outcomes (groups, values, analyses) when the trial has results."""
    proto = study.get("protocolSection") or {}
    lines = [f"Title: {(proto.get('identificationModule') or {}).get('briefTitle', '')}"]
    for o in (proto.get("outcomesModule") or {}).get("primaryOutcomes") or []:
        lines.append(f"Primary outcome (registered): {o.get('measure', '')}. {o.get('description', '')} "
                     f"Time frame: {o.get('timeFrame', '')}".strip())
    for m in ((study.get("resultsSection") or {}).get("outcomeMeasuresModule") or {}).get("outcomeMeasures") or []:
        if m.get("type") != "PRIMARY":
            continue
        groups = {g.get("id"): g.get("title", "") for g in m.get("groups") or []}
        lines.append(f"Primary outcome result: {m.get('title', '')}. {m.get('description', '')}".strip())
        for c in m.get("classes") or []:
            for cat in c.get("categories") or []:
                for v in cat.get("measurements") or []:
                    lines.append(f"{groups.get(v.get('groupId'), v.get('groupId'))}: {v.get('value', '')} "
                                 f"{m.get('unitOfMeasure', '')}".strip())
        for a in m.get("analyses") or []:
            lines.append(f"Analysis: {a.get('statisticalMethod', '')}, p = {a.get('pValue', '')}. "
                         f"{a.get('pValueComment', '') or ''}".strip())
    return "\n".join(lines)


def registry_text(nct: str) -> Optional[str]:
    """Cached registry text of a trial (see `_record_text`); "" when there is no such trial, None on network
    trouble."""
    global _records
    with _lock:
        if _records is None:
            _records = json.loads(RECORDS.read_text()) if RECORDS.exists() else {}
        if nct in _records:
            return _records[nct]
    text = None
    for attempt in range(4):
        try:
            r = httpx.get(f"{API}/{nct}", timeout=30)
        except httpx.HTTPError:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            text = ""
            break
        if r.status_code == 200:
            text = _record_text(r.json())
            break
        time.sleep(2 ** attempt)
    if text is None:
        return None
    with _lock:
        _records[nct] = text
        RECORDS.parent.mkdir(parents=True, exist_ok=True)
        RECORDS.write_text(json.dumps(_records, ensure_ascii=False, indent=0))
    return text

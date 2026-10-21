"""ChEBI classes of a compound for `analog_weak` in typed proximity (card spec 8b, agreed 2026-10-21): two
compounds of which at least one has no ChEMBL mechanism target are weak analogs when their most specific common
is_a ancestor is narrow, i.e. has at most `MAX_DESCENDANTS` descendants (the class size). Quercetin and fisetin:
7-hydroxyflavonol (41), then flavonols (81), hydroxyflavone (464), flavonoid (1,858); sirolimus and tacrolimus:
macrolide lactam (10), macrolide (1,619). ChEBI roles (has_role) are not used: the role "geroprotector" is shared
by rapamycin, quercetin, resveratrol, metformin and dasatinib alike. Source: the ChEBI ontology in OLS4 (EBI), no
key. Cached in data/cache/chebi.json; network errors are not cached."""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "chebi.json"
OLS = "https://www.ebi.ac.uk/ols4/api/v2/ontologies/chebi/classes/"
MAX_DESCENDANTS = 50                 # the class-size cap; chosen on the backtest pool (docs/rules-method.md)

_lock = threading.Lock()
_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    return _cache


def _get(chebi_id: str) -> Optional[dict]:
    """The OLS4 class record, or None when ChEBI has no such class; raises on network trouble."""
    iri = urllib.parse.quote(urllib.parse.quote(f"http://purl.obolibrary.org/obo/{chebi_id.replace(':', '_')}",
                                                safe=""), safe="")
    for attempt in range(4):
        try:
            r = httpx.get(OLS + iri, timeout=60)
        except httpx.HTTPError:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 200:
            return r.json()
        time.sleep(2 ** attempt)
    raise ConnectionError(chebi_id)


def _term(chebi_id: str) -> Optional[dict]:
    """{label, descendants, parents, ancestors} of a class (descendants = the class size), cached."""
    with _lock:
        hit = _load().get(chebi_id, "missing")
        if hit is None or (isinstance(hit, dict) and "ancestors" in hit):
            return hit
    try:
        r = _get(chebi_id)
    except ConnectionError:
        return None
    term = None if r is None else {
        "label": (r.get("label") or [""])[0], "descendants": int(r.get("numDescendants") or 0),
        "parents": [p.split("/")[-1].replace("_", ":") for p in r.get("directParent") or [] if "CHEBI_" in p],
        "ancestors": [p.split("/")[-1].replace("_", ":") for p in r.get("hierarchicalAncestor") or [] if "CHEBI_" in p]}
    with _lock:
        _load()[chebi_id] = term
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_cache, ensure_ascii=False, indent=0))
    return term


def classes(chebi_id: str, max_descendants: int = MAX_DESCENDANTS) -> list[tuple[str, str, int]]:
    """The compound's is_a ancestors with at most `max_descendants` descendants: [(CHEBI id, label, size)],
    most specific first."""
    term = _term(chebi_id) if chebi_id and chebi_id.startswith("CHEBI:") else None
    out = []
    for a in (term or {}).get("ancestors", []):
        t = _term(a)
        if t is not None and 0 < t["descendants"] <= max_descendants:
            out.append((a, t["label"], t["descendants"]))
    return sorted(out, key=lambda x: (x[2], x[0]))


def common_classes(a: str, b: str, max_descendants: int = 100000) -> list[tuple[str, str, int]]:
    """Common is_a ancestors of two compounds, most specific (smallest) first, for choosing the size cap."""
    ca = {c[0]: c for c in classes(a, max_descendants)}
    return [c for c in classes(b, max_descendants) if c[0] in ca]

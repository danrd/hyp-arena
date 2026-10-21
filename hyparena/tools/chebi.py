"""ChEBI classes of a compound for `analog` in typed proximity (card spec 8b: "different compounds sharing a
target or class ... ChEBI hierarchy"). Only the direct is_a parents, and only narrow ones (at most
`MAX_DESCENDANTS` descendants): "macrolide lactam" (10) joins rapamycin and the rapalogs, "7-hydroxyflavonol" (41)
quercetin and fisetin, while "ether" (9,036) or "polyphenol" (885) would make most compounds analogs. ChEBI roles
(has_role) are not used: the role "geroprotector" is shared by rapamycin, quercetin, resveratrol, metformin and
dasatinib alike. Source: the ChEBI ontology in OLS4 (EBI), no key. Cached in data/cache/chebi.json; network
errors are not cached."""
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
MAX_DESCENDANTS = 50

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
    """{label, descendants, parents} of a class, cached."""
    with _lock:
        if chebi_id in _load():
            return _load()[chebi_id]
    try:
        r = _get(chebi_id)
    except ConnectionError:
        return None
    term = None if r is None else {
        "label": (r.get("label") or [""])[0], "descendants": int(r.get("numDescendants") or 0),
        "parents": [p.split("/")[-1].replace("_", ":") for p in r.get("directParent") or [] if "CHEBI_" in p]}
    with _lock:
        _load()[chebi_id] = term
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_cache, ensure_ascii=False, indent=0))
    return term


def classes(chebi_id: str, max_descendants: int = MAX_DESCENDANTS) -> list[tuple[str, str]]:
    """Narrow direct parent classes of a compound: [(CHEBI id, label)]."""
    term = _term(chebi_id) if chebi_id and chebi_id.startswith("CHEBI:") else None
    out = []
    for p in (term or {}).get("parents", []):
        t = _term(p)
        if t is not None and 0 < t["descendants"] <= max_descendants:
            out.append((p, t["label"]))
    return out

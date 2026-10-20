"""Compound identifiers: a name → its PubChem parent compound (salts and hydrates collapse to the parent:
"quercetin dihydrate" and "quercetin" are the same compound), with the preferred name, InChIKey, ChEBI id
(from PubChem's synonyms), ChEMBL id and maximum clinical phase (ChEMBL, by InChIKey) and the synonyms.

Classes and mixtures ("senolytics", "omega-3 fatty acids") have no compound and stay unresolved: matching then
falls back to names. Results, including "not found", are cached on disk (data/cache/compounds.json); network
errors are not cached. The DrugAge compound names are mapped once into data/drugage_compounds.json
(`python -m hyparena.tools.compounds --drugage`)."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "compounds.json"
DRUGAGE_MAP = ROOT / "data" / "drugage_compounds.json"
PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"
PAUSE = 0.25                                   # PubChem allows 5 requests per second

_lock = threading.Lock()
_cache: Optional[dict] = None


@dataclass
class Compound:
    cid: int                                   # PubChem parent compound
    name: str                                  # PubChem title (preferred name)
    inchikey: str = ""
    chebi: str = ""                            # "CHEBI:9168"
    chembl: str = ""                           # "CHEMBL413"
    max_phase: Optional[int] = None            # ChEMBL max phase 0..4 (None: not in ChEMBL or no phase)
    synonyms: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        """The identifier written into the card: ChEBI when PubChem lists one, else the PubChem CID."""
        return self.chebi or f"PubChem:{self.cid}"


class LookupError_(Exception):
    """A network failure (not cached, unlike "not found")."""


def key(name: str) -> str:
    """Comparison key of a name: lower case, unicode dashes as "-", letters and digits only."""
    name = re.sub(r"[‐-―−]", "-", name or "").lower()
    return re.sub(r"[^a-z0-9α-ω]+", "", name)


def _get(url: str) -> Optional[dict]:
    """JSON or None for "not found"; raises LookupError_ on network trouble."""
    for attempt in range(4):
        try:
            r = httpx.get(url, timeout=30)
        except httpx.HTTPError:
            time.sleep(2 ** attempt)
            continue
        time.sleep(PAUSE)
        if r.status_code == 404:
            return None
        if r.status_code == 200:
            return r.json()
        if r.status_code in (400,):
            return None                        # PubChem: a name it cannot parse
        time.sleep(2 ** attempt)               # 503 "server busy" and the like
    raise LookupError_(url)


def parent_cid(name: str) -> Optional[int]:
    """PubChem parent CID of a name (first match), or None."""
    q = urllib.parse.quote(re.sub(r"[‐-―−]", "-", name.strip()), safe="")
    data = _get(f"{PUG}/compound/name/{q}/cids/JSON?cids_type=parent")
    cids = (data or {}).get("IdentifierList", {}).get("CID") or []
    return int(cids[0]) if cids and cids[0] else None


def _details(cid: int) -> Compound:
    props = (_get(f"{PUG}/compound/cid/{cid}/property/Title,InChIKey/JSON") or {}).get("PropertyTable", {}).get("Properties") or [{}]
    syn = ((_get(f"{PUG}/compound/cid/{cid}/synonyms/JSON") or {}).get("InformationList", {}).get("Information") or [{}])[0].get("Synonym") or []
    c = Compound(cid=cid, name=props[0].get("Title", ""), inchikey=props[0].get("InChIKey", ""),
                 chebi=next((s for s in syn if re.fullmatch(r"CHEBI:\d+", s)), ""),
                 synonyms=[s for s in syn if len(s) <= 60][:80])       # skip long systematic names
    if c.inchikey:
        mol = (_get(f"{CHEMBL}/molecule.json?molecule_structures__standard_inchi_key={c.inchikey}"
                    "&only=molecule_chembl_id,max_phase") or {}).get("molecules") or []
        if mol:
            c.chembl = mol[0].get("molecule_chembl_id") or ""
            phase = mol[0].get("max_phase")
            try:
                c.max_phase = max(0, min(4, int(float(phase)))) if phase is not None else None
            except ValueError:
                c.max_phase = None
    return c


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    return _cache


def _save() -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(_cache, ensure_ascii=False, indent=0))


def lookup(name: str) -> Optional[Compound]:
    """The compound a name stands for, or None (not a single compound, or not found). Cached."""
    k = key(name)
    if not k:
        return None
    with _lock:
        hit = _load().get(k, "missing")
    if hit != "missing":
        return Compound(**hit) if hit else None
    try:
        cid = parent_cid(name)
        comp = _details(cid) if cid else None
    except LookupError_:
        return None                            # try again next time
    with _lock:
        _load()[k] = asdict(comp) if comp else None
        _save()
    return comp


def split(label: str) -> list[str]:
    """Components of a combination label ("dasatinib + quercetin", "dasatinib plus quercetin")."""
    parts = re.split(r"\s*(?:\+|,|;|\bplus\b|\band\b|\bwith\b|/)\s*", label or "", flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def cids(label: str) -> Optional[frozenset[int]]:
    """Parent CIDs of every component of a label; None when any component does not resolve."""
    out = set()
    for part in split(label):
        c = lookup(part)
        if c is None:
            return None
        out.add(c.cid)
    return frozenset(out) or None


# ---- DrugAge names ----

def drugage_map() -> dict[str, Optional[int]]:
    """DrugAge compound name key → parent CID (None: not a single compound), from the committed table."""
    return json.loads(DRUGAGE_MAP.read_text()) if DRUGAGE_MAP.exists() else {}


def build_drugage_map(log=print, workers: int = 3) -> dict:
    from concurrent.futures import ThreadPoolExecutor
    from hyparena.backtest import drugage_rows
    names = sorted({r["compound_name"] for r in drugage_rows()})
    out = dict(drugage_map())
    todo = [n for n in names if key(n) not in out]

    def one(n):
        try:
            return n, parent_cid(n), True
        except LookupError_:
            return n, None, False

    with ThreadPoolExecutor(max_workers=workers) as pool:          # PubChem allows 5 requests per second
        for i, (n, cid, ok) in enumerate(pool.map(one, todo), 1):
            if ok:
                out[key(n)] = cid
            else:
                log(f"network error, skipped: {n}")
            if i % 100 == 0:
                log(f"{len(names) - len(todo) + i}/{len(names)}")
                DRUGAGE_MAP.write_text(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=True))
    DRUGAGE_MAP.write_text(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=True))
    log(f"DrugAge names: {len(names)}; resolved to a compound: {sum(1 for v in out.values() if v)}")
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drugage", action="store_true", help="map every DrugAge compound name to a PubChem parent CID")
    ap.add_argument("names", nargs="*")
    args = ap.parse_args()
    if args.drugage:
        build_drugage_map()
    for n in args.names:
        print(n, "→", lookup(n))


if __name__ == "__main__":
    main()

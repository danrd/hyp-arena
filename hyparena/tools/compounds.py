"""Compound identifiers: a name → its PubChem parent compound (salts and hydrates collapse to the parent:
"quercetin dihydrate" and "quercetin" are the same compound), with the preferred name, InChIKey, ChEBI id
(from PubChem's synonyms), ChEMBL id, maximum clinical phase, first approval year, mechanism targets and ATC codes
(ChEMBL, by InChIKey; targets and ATC over the molecule's salt and hydrate forms) and the synonyms.

Classes and mixtures ("senolytics", "omega-3 fatty acids") have no compound and stay unresolved: matching then
falls back to names. Results, including "not found", are cached on disk (data/cache/compounds.json); network
errors are not cached. The DrugAge compound names are mapped once into data/drugage_compounds.json
(`python -m hyparena.tools.compounds --drugage`)."""
from __future__ import annotations

import functools
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
    first_approval: Optional[int] = None       # ChEMBL year of first approval (None: not approved or unknown)
    targets: Optional[list[str]] = None        # ChEMBL mechanism targets (target ChEMBL ids); None: not fetched
    atc: Optional[list[str]] = None            # ATC codes (level 5) of the molecule and its salt / hydrate forms
    chembl_rev: int = 0                        # how the ChEMBL fields were fetched (CHEMBL_REV); older entries are refetched
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


@functools.lru_cache(maxsize=1)
def _aliases() -> dict[str, str]:
    """Abbreviations of configs/compound_aliases.yaml, keyed by `key`."""
    import yaml
    path = ROOT / "configs" / "compound_aliases.yaml"
    raw = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("aliases", {}) if path.exists() else {}
    return {key(a): full for a, full in raw.items()}


GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ω": "omega"}


def resolve_alias(name: str) -> str:
    """The full name of a standard abbreviation (DNP, MB, β-GPA), else the name itself; Greek letters spelled out ("17α-estradiol" and
    "17-alpha-estradiol" are one name) after the abbreviation table, which keys some abbreviations by their Greek letter."""
    full = _aliases().get(key(name), name)
    for g, latin in GREEK.items():
        full = re.sub(rf"(?<=\d){g}", f"-{latin}", full)
        full = full.replace(g, latin)
    return full


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


ACTIVE_METALS = re.compile(
    r"\b(lithium|barium|strontium|zinc|cupric|cuprous|copper|ferric|ferrous|iron|nickel|nickelous|cobalt|cobaltous|"
    r"manganese|manganous|cadmium|mercuric|mercury|lead|alumin(?:i)?um|silver|gold|chromium|chromic|vanadium|"
    r"vanadyl|selen\w*|tin|stannous|platinum|palladium|ruthenium|bismuth|molybd\w*|tungst\w*|arsen\w*|antimony|"
    r"thallium|cesium|caesium|rubidium|titanium)\b", re.I)
COUNTER_IONS = re.compile(r"\b(sodium|disodium|potassium|calcium|magnesium|ammonium)\b", re.I)
INORGANIC = re.compile(r"^\s*(?:(?:di|tri)?(?:chloride|sulfate|sulphate|nitrate|phosphate|carbonate|bicarbonate|"
                       r"hydroxide|oxide|iodide|bromide|fluoride|selenite|selenate)\s*)+$", re.I)


def keeps_own_compound(name: str) -> bool:
    """PubChem's parent drops metal counter-ions, which makes zinc, nickel and barium acetate all "acetic acid".
    A name keeps its own compound when the metal is the active part: lithium, transition and heavy metals,
    selenium; or sodium, potassium, calcium, magnesium with an inorganic anion (sodium chloride). As counter-ions
    of an organic compound they collapse (dexamethasone sodium phosphate = dexamethasone)."""
    if ACTIVE_METALS.search(name):
        return True
    return bool(COUNTER_IONS.search(name)) and bool(INORGANIC.match(COUNTER_IONS.sub(" ", name)))


def parent_cid(name: str) -> Optional[int]:
    """PubChem parent CID of a name (first match), or None; see `keeps_own_compound`."""
    q = urllib.parse.quote(re.sub(r"[‐-―−]", "-", name.strip()), safe="")
    kind = "" if keeps_own_compound(name) else "?cids_type=parent"
    data = _get(f"{PUG}/compound/name/{q}/cids/JSON{kind}")
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
                    "&only=molecule_chembl_id,max_phase,first_approval") or {}).get("molecules") or []
        if mol:
            _chembl_fields(c, mol[0])
            c.targets, c.atc, c.chembl_rev = _targets(c.chembl), _atc(c.chembl), CHEMBL_REV
    return c


CHEMBL_REV = 2       # 2: mechanisms and ATC over the parent and all its forms (metformin's are on its salt)


def _targets(chembl: str) -> list[str]:
    """Targets of the mechanisms of action of a parent molecule and its salt / hydrate forms in ChEMBL
    (rapamycin, everolimus, temsirolimus: FKBP1A; metformin's sit on metformin hydrochloride)."""
    if not chembl:
        return []
    data = _get(f"{CHEMBL}/mechanism.json?parent_molecule_chembl_id={chembl}&only=target_chembl_id&limit=100") or {}
    return sorted({m["target_chembl_id"] for m in data.get("mechanisms") or [] if m.get("target_chembl_id")})


def _atc(chembl: str) -> list[str]:
    """ATC codes of a parent molecule and its forms (tacrolimus's are on tacrolimus monohydrate)."""
    if not chembl:
        return []
    forms = (_get(f"{CHEMBL}/molecule_form.json?parent_chembl_id={chembl}&limit=100") or {}).get("molecule_forms") or []
    ids = sorted({chembl} | {f["molecule_chembl_id"] for f in forms if f.get("molecule_chembl_id")})
    codes = set()
    for m in ids:
        codes |= set((_get(f"{CHEMBL}/molecule/{m}.json?only=atc_classifications") or {}).get("atc_classifications") or [])
    return sorted(codes)


def _chembl_fields(c: Compound, mol: dict) -> None:
    c.chembl = mol.get("molecule_chembl_id") or ""
    phase = mol.get("max_phase")
    try:
        c.max_phase = max(0, min(4, int(float(phase)))) if phase is not None else None
    except ValueError:
        c.max_phase = None
    year = mol.get("first_approval")
    c.first_approval = int(year) if isinstance(year, (int, float)) or (isinstance(year, str) and year.isdigit()) else None


def _upgrade(hit: dict) -> dict:
    """Cache entries written before `first_approval`, or before the current way of fetching targets and ATC
    codes (CHEMBL_REV): fetch them from ChEMBL once."""
    c = Compound(**hit)
    if c.chembl and "first_approval" not in hit:
        mol = (_get(f"{CHEMBL}/molecule/{c.chembl}.json?only=molecule_chembl_id,max_phase,first_approval") or {})
        if mol:
            _chembl_fields(c, mol)
    if hit.get("chembl_rev", 0) < CHEMBL_REV:
        c.targets, c.atc, c.chembl_rev = _targets(c.chembl), _atc(c.chembl), CHEMBL_REV
    return asdict(c)


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
    name = resolve_alias(name)
    k = key(name)
    if not k:
        return None
    with _lock:
        hit = _load().get(k, "missing")
    if isinstance(hit, dict) and ("first_approval" not in hit or hit.get("chembl_rev", 0) < CHEMBL_REV):
        try:
            hit = _upgrade(hit)
        except LookupError_:
            return Compound(**hit)
        with _lock:
            _load()[k] = hit
            _save()
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

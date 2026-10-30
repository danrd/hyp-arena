"""Reference pool for the extraction check (planned L1.17): abstracts with a gold annotation.

    python -m scripts.extraction_pool build        # needs network (DrugAge download, PubMed); writes to $EXTRACTION_POOL_DIR (default runs/extraction/, not tracked: the abstracts are publishers' texts and this repository is public)

Part A: 60 papers of the current DrugAge release (lifespan, one species each, abstract in PubMed), the curated rows are the gold
(compound, species, strain, dose, sex, change of average lifespan, significance). Selection by a hash of the PMID, stratified
by species (mouse 25, worm 15, fly 15, rat 5).
Part B: 50 abstracts that are NOT in DrugAge: lifespan intervention papers found with queries that favour null and negative results;
annotated by hand in the format of `annotation_schema.md` (a first draft by Jules, rechecked by Claude: at least 30% at random and every item flagged ambiguous).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

OUT = Path(os.environ.get("EXTRACTION_POOL_DIR", "runs/extraction"))      # abstracts are publishers' texts: never inside the public repository
STRATA = {"Mus musculus": 25, "Caenorhabditis elegans": 15, "Drosophila melanogaster": 15, "Rattus norvegicus": 5}
QUERIES = [
    "dietary supplement did not extend lifespan mice no significant effect on lifespan",
    "no effect on lifespan C. elegans compound treatment not extend lifespan",
    "Drosophila lifespan drug treatment no increase in lifespan",
    "lifespan shortened treatment mice significantly decreased survival drug",
    "interventions testing program lifespan null result",
]


def _h(pmid: str) -> str:
    return hashlib.sha1(pmid.encode()).hexdigest()


def part_a() -> list[dict]:
    from hyparena.backtest import drugage_rows
    from hyparena.tools import pubmed
    by = defaultdict(list)
    for r in drugage_rows():
        pm = (r.get("pubmed_id") or "").strip()
        if pm.isdigit():
            by[(pm, r["species"].strip())].append(r)
    cands = defaultdict(list)
    for (pm, sp), rows in by.items():
        if sp in STRATA and len({x["compound_name"] for x in rows}) <= 3:
            cands[sp].append(pm)
    out = []
    for sp, n in STRATA.items():
        pms = sorted(set(cands[sp]), key=_h)
        got = pubmed.fetch(pms[: n * 3])
        for pm in pms[: n * 3]:
            a = got.get(pm)
            if not a or not a.get("abstract") or len(a["abstract"]) < 500 or pubmed.is_review(a):
                continue
            rows = by[(pm, sp)]
            out.append({"pmid": pm, "species": sp, "title": a["title"], "year": a.get("year"), "abstract": a["abstract"],
                        "gold": [{"compound": r["compound_name"], "species": sp, "strain": r["strain"], "dosage": r["dosage"],
                                  "sex": r["gender"], "avg_change_percent": r["avg_lifespan_change_percent"],
                                  "avg_significance": r["avg_lifespan_significance"]} for r in rows]})
            if sum(1 for x in out if x["species"] == sp) >= n:
                break
    return out


def part_b(exclude: set[str]) -> list[dict]:
    from hyparena.backtest import drugage_rows
    from hyparena.tools import pubmed
    known = {(r.get("pubmed_id") or "").strip() for r in drugage_rows()} | exclude
    pmids = []
    for q in QUERIES:
        for p in pubmed.search(q, retmax=40):
            if p not in known and p not in pmids:
                pmids.append(p)
    pmids.sort(key=_h)
    got = pubmed.fetch(pmids[:150])
    out = []
    for pm in pmids[:150]:
        a = got.get(pm)
        if a and a.get("abstract") and 700 <= len(a["abstract"]) <= 3500 and not pubmed.is_review(a):
            out.append({"pmid": pm, "title": a["title"], "year": a.get("year"), "abstract": a["abstract"]})
        if len(out) >= 50:
            break
    return out


# Part C (L1.17c, 2026-10-30): part B's free-text queries returned many papers that are not intervention studies (19 of 35
# annotated had no observation: epidemiology, editorials, catheters). Part C asks PubMed for the MeSH heading Longevity/drug effects
# (indexers' mark for an agent acting on lifespan) AND a model organism AND a null or negative wording, no reviews and keeps an abstract only if code finds an intervention, a lifespan
# term, the organism and a null or negative wording in it. Only PMIDs are written to this repository.
NULL_TIAB = ('("no significant"[tiab] OR "did not extend"[tiab] OR "did not increase"[tiab] OR "failed to extend"[tiab] OR '
             '"no effect on lifespan"[tiab] OR "no effect on life span"[tiab] OR "not extend"[tiab] OR "shortened"[tiab] OR '
             '"reduced lifespan"[tiab] OR "decreased lifespan"[tiab] OR "reduced life span"[tiab] OR "decreased life span"[tiab])')
LIFESPAN_TIAB = '(lifespan[tiab] OR "life span"[tiab] OR longevity[tiab])'
INTERVENTION_TIAB = '(treat*[tiab] OR supplement*[tiab] OR administ*[tiab] OR fed[tiab] OR feeding[tiab] OR drug*[tiab] OR compound*[tiab] OR dose*[tiab])'
PART_C_STRATA = {"mouse": ("mice[MeSH Terms]", r"\bmice\b|\bmouse\b", 15),
                 "worm": ('"Caenorhabditis elegans"[MeSH Terms]', r"elegans|nematode", 15),
                 "fly": ("Drosophila[MeSH Terms]", r"drosophila|\bflies\b|\bfly\b", 15),
                 "rat": ("rats[MeSH Terms]", r"\brats?\b", 5)}
NULL_RE = (r"no significant|not significant|did not (?:extend|increase|prolong|affect|alter|change)|failed to (?:extend|increase|prolong)|"
           r"no (?:effect|change|difference)|not (?:extend|prolong)|shorten|reduced (?:the )?(?:mean |median |maximum )?(?:lifespan|life span)|"
           r"decreased (?:the )?(?:mean |median |maximum )?(?:lifespan|life span)")
INTERVENTION_RE = r"treat|supplement|administ|\bfed\b|feeding|\bdiet|drug|compound|dose|dosage"


def part_c(exclude: set[str], per_query: int = 300) -> list[dict]:
    import re
    from hyparena.backtest import drugage_rows
    from hyparena.tools import pubmed
    known = {(r.get("pubmed_id") or "").strip() for r in drugage_rows()} | exclude
    out = []
    for sp, (mesh, sp_re, n) in PART_C_STRATA.items():
        q = f'"Longevity/drug effects"[MeSH Terms] AND {mesh} AND {NULL_TIAB} AND english[lang] NOT review[pt]'
        pmids = sorted((p for p in pubmed.search(q, retmax=per_query) if p not in known), key=_h)
        got, taken = pubmed.fetch(pmids), 0
        for pm in pmids:
            a = got.get(pm)
            if not a or not a.get("abstract") or not 700 <= len(a["abstract"]) <= 3500 or pubmed.is_review(a):
                continue
            t = (a["title"] + " " + a["abstract"]).lower()
            if not (re.search(r"lifespan|life span|longevity", t) and re.search(sp_re, t) and re.search(NULL_RE, t)
                    and re.search(INTERVENTION_RE, t)):
                continue
            out.append({"pmid": pm, "species": sp, "title": a["title"], "year": a.get("year"), "abstract": a["abstract"]})
            known.add(pm)
            taken += 1
            if taken >= n:
                break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build", "part-c"])
    ap.add_argument("--exclude", nargs="*", default=[], help="files with PMIDs (one per line or a JSON list) never chosen for part C")
    args = ap.parse_args()
    if args.cmd == "part-c":
        import re
        ex = set()
        for f in args.exclude:
            ex |= set(re.findall(r"\b\d{6,9}\b", Path(f).read_text()))
        c = part_c(ex)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "to_annotate_part_c.json").write_text(json.dumps({"papers": c}, ensure_ascii=False, indent=1))
        from collections import Counter
        print("part C:", len(c), dict(Counter(x["species"] for x in c)), "excluded", len(ex))
        return
    OUT.mkdir(parents=True, exist_ok=True)
    a = part_a()
    (OUT / "gold_drugage.json").write_text(json.dumps({"source": "DrugAge (HAGR, CC BY 3.0), current release", "papers": a}, ensure_ascii=False, indent=1))
    b = part_b({x["pmid"] for x in a})
    (OUT / "to_annotate.json").write_text(json.dumps({"papers": b}, ensure_ascii=False, indent=1))
    from collections import Counter
    print("part A:", len(a), dict(Counter(x["species"] for x in a)), "| part B:", len(b))


if __name__ == "__main__":
    main()

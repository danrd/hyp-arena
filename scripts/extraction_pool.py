"""Reference pool for the extraction check (planned L1.17): abstracts with a gold annotation.

    python -m scripts.extraction_pool build        # needs network (DrugAge download, PubMed); writes data/validation/extraction/

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
from collections import defaultdict
from pathlib import Path

OUT = Path("data/validation/extraction")
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build"])
    ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    a = part_a()
    (OUT / "gold_drugage.json").write_text(json.dumps({"source": "DrugAge (HAGR, CC BY 3.0), current release", "papers": a}, ensure_ascii=False, indent=1))
    b = part_b({x["pmid"] for x in a})
    (OUT / "to_annotate.json").write_text(json.dumps({"papers": b}, ensure_ascii=False, indent=1))
    from collections import Counter
    print("part A:", len(a), dict(Counter(x["species"] for x in a)), "| part B:", len(b))


if __name__ == "__main__":
    main()

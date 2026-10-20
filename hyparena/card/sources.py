"""Curated evidence for lifespan claims from DrugAge (HAGR, CC BY 3.0): deterministic, no LLM. One record per
publication and species for the claim's compound: supporting if any row of that paper reports a significant
increase of average or maximum lifespan (the relation covers mean, median and maximum lifespan), counter if
no row does (no significant effect, or a decrease). A non-significant average alone is not a refutation:
e.g. PMID 22107964 reports a longer lifespan of the last survivors while DrugAge lists the mean as NS. Records keep
the paper (linked PMID), so they do not add robustness on top of the paper itself."""
from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache
from typing import Optional

from hyparena.card.models import Claim, EvidenceRecord, ProgramInfo
from hyparena.tools.compounds import drugage_map, key as cp_key

SPECIES = {"mouse": "Mus musculus", "mice": "Mus musculus", "mus musculus": "Mus musculus", "ncbitaxon:10090": "Mus musculus",
           "rat": "Rattus norvegicus", "ncbitaxon:10116": "Rattus norvegicus",
           "worm": "Caenorhabditis elegans", "c. elegans": "Caenorhabditis elegans", "caenorhabditis elegans": "Caenorhabditis elegans",
           "ncbitaxon:6239": "Caenorhabditis elegans", "fly": "Drosophila melanogaster", "drosophila": "Drosophila melanogaster",
           "drosophila melanogaster": "Drosophila melanogaster", "ncbitaxon:7227": "Drosophila melanogaster",
           "yeast": "Saccharomyces cerevisiae", "saccharomyces cerevisiae": "Saccharomyces cerevisiae"}


@lru_cache(maxsize=1)
def _rows() -> list[dict]:
    from hyparena.backtest import drugage_rows
    return drugage_rows()


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower().replace("‐", "-"))


def _pct(v: str) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def drugage_records(claim: Claim, allowed_pmids: Optional[set[str]] = None,
                    cid: Optional[int] = None) -> tuple[list[EvidenceRecord], list[EvidenceRecord]]:
    """(evidence, counterevidence) for an `extends_lifespan_in` claim; empty for other relations or unknown
    species. `allowed_pmids` restricts to papers published by an as-of date. `cid`: the PubChem parent compound
    of the claim's subject; DrugAge rows then match by compound (sirolimus = rapamycin, quercetin dihydrate =
    quercetin), and by name otherwise."""
    if claim.relation != "extends_lifespan_in":
        return [], []
    species = None
    for text in (claim.object.id or "", claim.object.label, claim.qualifiers.get("species", "")):
        species = SPECIES.get(text.strip().lower())
        if species:
            break
    if not species:
        return [], []
    target = _key(claim.subject.label)
    names = drugage_map() if cid else {}

    def same(name: str) -> bool:
        mapped = names.get(cp_key(name))
        return mapped == cid if cid and mapped else _key(name) == target

    by_paper = defaultdict(list)
    for r in _rows():
        if r["species"].strip() == species and same(r["compound_name"]) and r["pubmed_id"].strip():
            by_paper[r["pubmed_id"].strip()].append(r)
    support, against = [], []
    for pmid, rows in sorted(by_paper.items()):
        if allowed_pmids is not None and pmid not in allowed_pmids:
            continue
        pos = [r for r in rows if (r["avg_lifespan_significance"].strip() == "S" and (_pct(r["avg_lifespan_change_percent"]) or 0) > 0)
               or (r["max_lifespan_significance"].strip() == "S" and (_pct(r["max_lifespan_change_percent"]) or 0) > 0)]
        neg = [r for r in rows if r["avg_lifespan_significance"].strip() == "S" and (_pct(r["avg_lifespan_change_percent"]) or 0) < 0]
        ns = [r for r in rows if r["avg_lifespan_significance"].strip() == "NS"]
        use = pos or neg or ns
        if not use:
            continue
        sexes = sorted({s for r in use for s in (["male"] if r["gender"].lower() == "male" else ["female"] if r["gender"].lower() == "female"
                                                  else ["male", "female"] if r["gender"].lower() in ("both", "pooled") else [])})
        itp = any(r.get("ITP", "").strip().lower() == "yes" for r in use)
        sizes = [p for p in (_pct(r["avg_lifespan_change_percent"]) for r in use) if p is not None]
        rec = EvidenceRecord(
            source="DrugAge", record_id=f"DrugAge:{rows[0]['compound_name']}/{species}/PMID{pmid}", epistemic_type="B_curated",
            linked_pmid=pmid, lab_or_cohort=f"PMID:{pmid}", species=species, endpoint="lifespan", quote_role="finding",
            metric="average lifespan", effect_percent=max(sizes) if pos and sizes else None, sexes=sexes,
            qualifiers_match={"species": "yes", "intervention_match": "exact"},
            program=ProgramInfo(name="ITP") if itp else None,
            fields={"rows": len(use), "significance": "S" if pos or neg else "NS",
                    "avg_lifespan_change_percent": ", ".join(r["avg_lifespan_change_percent"] for r in use[:6]),
                    "dosage": "; ".join(sorted({r["dosage"] for r in use}))[:200]},
            notes="DrugAge rows for this paper" + (" (ITP)" if itp else ""))
        (support if pos else against).append(rec)
    return support, against

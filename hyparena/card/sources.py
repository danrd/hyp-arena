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

from hyparena.card import contexts
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


NEGATED = ("no_effect", "none", "no", "not", "no effect")


def lifespan_wanted(claim) -> Optional[str]:
    """The direction of effect a lifespan claim asserts: increase, decrease or no_effect (a negated "extends",
    `qualifiers.direction` no_effect, asserts no effect); None for other relations."""
    relation = claim.relation
    if relation == "extends_lifespan_in" and claim.qualifiers.get("direction", "").lower() in NEGATED:
        return "no_effect"
    return {"extends_lifespan_in": "increase", "shortens_lifespan_in": "decrease",
            "no_lifespan_effect_in": "no_effect"}.get(relation)


def _sex(rows: list[dict]) -> str:
    g = {r["gender"].strip().lower() for r in rows}
    if g & {"both", "pooled"} or {"male", "female"} <= g:
        return "both"
    return "male" if g == {"male"} else "female" if g == {"female"} else "unknown"


def _record(rows: list[dict], pmid: str, species: str, suffix: str = "") -> Optional[EvidenceRecord]:
    """One curated record for the rows of a paper (and strain); its category: increase, decrease or none."""
    pos = [r for r in rows if (r["avg_lifespan_significance"].strip() == "S" and (_pct(r["avg_lifespan_change_percent"]) or 0) > 0)
           or (r["max_lifespan_significance"].strip() == "S" and (_pct(r["max_lifespan_change_percent"]) or 0) > 0)]
    neg = [r for r in rows if r["avg_lifespan_significance"].strip() == "S" and (_pct(r["avg_lifespan_change_percent"]) or 0) < 0]
    ns = [r for r in rows if r["avg_lifespan_significance"].strip() == "NS"]
    use = pos or neg or ns
    if not use:
        return None
    itp = any(r.get("ITP", "").strip().lower() == "yes" for r in use)
    sizes = [p for p in (_pct(r["avg_lifespan_change_percent"]) for r in use) if p is not None]
    joined = lambda key: "; ".join(sorted({r.get(key, "").strip() for r in use} - {""}))
    rec = EvidenceRecord(
        source="DrugAge", record_id=f"DrugAge:{rows[0]['compound_name']}/{species}/PMID{pmid}{suffix}", epistemic_type="B_curated",
        linked_pmid=pmid, lab_or_cohort=f"PMID:{pmid}", species=species, endpoint="lifespan", quote_role="finding",
        metric="average lifespan", effect_percent=max(sizes) if pos and sizes else None, sex=_sex(use),
        strain=joined("strain"), dose=joined("dosage")[:200], age_at_start=joined("age_at_initiation"),
        qualifiers_match={"species": "yes", "intervention_match": "exact"},
        program=ProgramInfo(name="ITP") if itp else None,
        fields={"rows": len(use), "significance": "S" if pos or neg else "NS",
                "avg_lifespan_change_percent": ", ".join(r["avg_lifespan_change_percent"] for r in use[:6]),
                "dosage": joined("dosage")[:200]},
        notes="DrugAge rows for this paper" + (" (ITP)" if itp else ""))
    category = "increase" if pos else "decrease" if neg else "none"
    rec.fields["category"] = category
    rec.effect = {"increase": "increase", "decrease": "decrease", "none": "no_effect"}[category]
    for strain in sorted({r.get("strain", "").strip() for r in use} - {""}):
        contexts.flag(rec, strain=strain)
    return rec


ROUTES = [("water", r"drinking water|\bin water\b|\bwater\b"),
          ("diet", r"\bppm\b|\bfood\b|\bdiet\b|\bchow\b|\bfeed\b"),
          ("injection", r"inject|\bi\.p\.|\bip\b|intraperitoneal|subcutaneous|\bs\.c\.|intravenous"),
          ("oral", r"gavage|\boral\b|\bp\.o\."), ("topical", r"topical")]
INTERMITTENT = r"intermittent|weekly|per week|/ ?week|a week|every (?:other|\d+|second|third)|once every|pulse|cycl|alternate|on/off|days? on"


def dose_route(text: str) -> str:
    """The route a DrugAge dosage names: diet (ppm in food), water (in drinking water), injection, oral, topical."""
    low = (text or "").lower()
    return next((route for route, pat in ROUTES if re.search(pat, low)), "unknown")


def intermittent(text: str) -> bool:
    return bool(re.search(INTERMITTENT, (text or "").lower()))


def curated_intervention_match(card, rec: EvidenceRecord) -> str:
    """Spec 7, rules over fields (no free-text comparison of regimens): the card's route differs from the
    record's → regimen_differs; the card's regimen is intermittent or weekly and the record's dosing is
    continuous → regimen_differs; else exact. dose_differs is never set by code."""
    route = dose_route(rec.dose)
    for i in card.pico.intervention:
        if i.route not in ("unknown", "other") and route != "unknown" and route != i.route:
            return "regimen_differs"
        if intermittent(i.regimen) and rec.dose and not intermittent(rec.dose):
            return "regimen_differs"
    return "exact"


def drugage_records(claim: Claim, allowed_pmids: Optional[set[str]] = None,
                    cid: Optional[int] = None) -> tuple[list[EvidenceRecord], list[EvidenceRecord]]:
    """(evidence, counterevidence) for a lifespan claim (extends, shortens, no effect; a negated "extends" with
    `qualifiers.direction` no_effect counts as no effect); empty for other relations or unknown species. Each
    paper falls in one category, increase (a significant increase of average or maximum lifespan), decrease
    (a significant decrease of average lifespan, and no increase) or none, which supports the matching relation
    and counts against the other two. `allowed_pmids` restricts to papers published by an as-of date. `cid`: the PubChem parent compound
    of the claim's subject; DrugAge rows then match by compound (sirolimus = rapamycin, quercetin dihydrate =
    quercetin), and by name otherwise."""
    wanted = {"increase": "increase", "decrease": "decrease", "no_effect": "none"}.get(lifespan_wanted(claim))
    if wanted is None:
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
    for pmid, paper_rows in sorted(by_paper.items()):
        if allowed_pmids is not None and pmid not in allowed_pmids:
            continue
        strains = sorted({r.get("strain", "").strip() for r in paper_rows})
        for strain in strains:                            # one record per strain: the strain rule compares them (spec 7)
            rows = [r for r in paper_rows if r.get("strain", "").strip() == strain]
            suffix = f"/{strain}" if len(strains) > 1 and strain else ""
            rec = _record(rows, pmid, species, suffix)
            if rec is None:
                continue
            (support if rec.fields["category"] == wanted else against).append(rec)
    return support, against

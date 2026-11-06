"""Two indicators from public data, no model calls (specs/trend-genetics-2026-11-06.yaml):

- trend_pubmed: is the intervention gaining attention in the literature, as of T: ln((a+1)/(b+1)) - ln(N_A/N_B) with a, b
  the PubMed records on the term in [T-3y, T) and [T-6y, T-3y) and N the records of all PubMed in the same windows;
  trend_trials: the same term among ClinicalTrials.gov interventions, trials by start date (secondary);
- genetic_support: does human genetics back the intervention's target: none < aging_gene < human_genetic, from the
  OpenGenes snapshot (data/cache/opengenes.json); unknown without a target gene.

Counts are cached in data/cache/trend_counts.json.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import time
from pathlib import Path
from typing import Optional

import httpx

from hyparena.card.models import HypothesisCard
from hyparena.tools import pubmed

ROOT = Path(__file__).resolve().parents[2]
COUNTS = ROOT / "data" / "cache" / "trend_counts.json"
OPENGENES = ROOT / "data" / "cache" / "opengenes.json"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
STOP = {"with", "from", "that", "this", "plus", "versus", "group", "program", "programme", "intervention", "therapy",
        "treatment", "training", "based", "placebo", "control", "older", "adults", "elderly", "daily", "dose", "oral",
        "supplementation", "supplement", "standard", "usual", "care"}
HUMAN_CAUSES = {"Association of genetic variants and gene expression levels with longevity",
                "Association of the gene with accelerated aging in humans"}
GENETIC_LEVELS = ("none", "aging_gene", "human_genetic")

_counts: Optional[dict] = None


def _cache() -> dict:
    global _counts
    if _counts is None:
        _counts = json.loads(COUNTS.read_text()) if COUNTS.exists() else {}
    return _counts


def _save() -> None:
    COUNTS.parent.mkdir(parents=True, exist_ok=True)
    COUNTS.write_text(json.dumps(_cache(), indent=0))


def _windows(as_of: str) -> tuple[tuple[str, str], tuple[str, str]]:
    a = as_of[:10] + ("-01" if len(as_of[:10]) == 7 else "-01-01" if len(as_of[:10]) == 4 else "")
    t = dt.date.fromisoformat(a)
    y = lambda k: t.replace(year=t.year - k) if not (t.month == 2 and t.day == 29) else t.replace(year=t.year - k, day=28)
    day = dt.timedelta(days=1)
    return (y(3).isoformat(), (t - day).isoformat()), (y(6).isoformat(), (y(3) - day).isoformat())


def pubmed_count(term: str, lo: str, hi: str) -> int:
    k = f"pm|{term}|{lo}|{hi}"
    c = _cache()
    if k not in c:
        params = {"db": "pubmed", "term": term, "retmax": 0, "retmode": "json", "datetype": "pdat",
                  "mindate": lo.replace("-", "/"), "maxdate": hi.replace("-", "/")}
        for attempt in range(5):
            res = pubmed._get("esearch.fcgi", params).json().get("esearchresult", {})
            if "ERROR" not in res and "count" in res:
                c[k] = int(res["count"])
                break
            time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"PubMed count failed for {term!r}")
        _save()
    return c[k]


def trials_count(term: str, lo: str, hi: str) -> int:
    k = f"ct|{term}|{lo}|{hi}"
    c = _cache()
    if k not in c:
        params = {"query.intr": term, "query.term": f"AREA[StartDate]RANGE[{lo},{hi}]", "countTotal": "true", "pageSize": 1,
                  "format": "json"}
        for attempt in range(5):
            try:
                r = httpx.get(CTGOV, params=params, timeout=40)
                if r.status_code == 400:                 # a query CT.gov cannot parse: unknown, not zero
                    c[k] = -1
                    break
                r.raise_for_status()
                c[k] = int(r.json().get("totalCount", 0))
                break
            except (httpx.HTTPError, ValueError):
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        _save()
    return c[k]


def clean_label(label: str) -> str:
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", label or "")
    s = re.split(r"[:;]", s)[0]
    return " ".join(re.sub(r"[^\w\s\-+/]", " ", s).split()).strip()


def words(label: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", label) if w.lower() not in STOP]


def terms(card: HypothesisCard) -> list[str]:
    """Candidate PubMed queries for the first intervention label: the phrase, then its content words."""
    labs = [i.label for i in card.pico.intervention]
    if not labs:
        return []
    lab = clean_label(labs[0])
    out = [f'"{lab}"[tiab]'] if lab else []
    ws = words(lab)
    if len(ws) > 1:
        out.append(" AND ".join(f"{w}[tiab]" for w in ws))
    return out


def trend_pubmed(card: HypothesisCard, as_of: str) -> tuple[Optional[float], str]:
    (a0, a1), (b0, b1) = _windows(as_of)
    NA, NB = pubmed_count("all[sb]", a0, a1), pubmed_count("all[sb]", b0, b1)
    for q in terms(card):
        a, b = pubmed_count(q, a0, a1), pubmed_count(q, b0, b1)
        if a + b >= 5:
            return round(math.log((a + 1) / (b + 1)) - math.log(NA / NB), 4), q
    return None, ""


def trend_trials(card: HypothesisCard, as_of: str) -> Optional[float]:
    labs = [i.label for i in card.pico.intervention]
    if not labs:
        return None
    lab = clean_label(labs[0])
    if not lab or len(lab.split()) > 6:                 # long descriptive labels: no usable registry query
        return None
    (a0, a1), (b0, b1) = _windows(as_of)
    a, b = trials_count(lab, a0, a1), trials_count(lab, b0, b1)
    if a < 0 or b < 0:
        return None
    return round(math.log((a + 1) / (b + 1)), 4) if a + b >= 3 else None


_genes: Optional[dict] = None


def opengenes() -> dict[str, dict]:
    """symbol or alias (lower case) -> {symbol, confidence, human}."""
    global _genes
    if _genes is None:
        _genes = {}
        for g in json.loads(OPENGENES.read_text())["items"]:
            rec = {"symbol": g["symbol"], "confidence": (g.get("confidenceLevel") or {}).get("name"),
                   "human": any(c.get("name") in HUMAN_CAUSES for c in g.get("commentCause") or [])}
            for name in [g["symbol"], *(g.get("aliases") or [])]:
                _genes.setdefault(name.lower(), rec)
    return _genes


def target_genes(card: HypothesisCard) -> tuple[set[str], set[str]]:
    """(gene-like names found, OpenGenes symbols among them): ChEMBL mechanism targets of the card's compounds and claim
    subjects / objects that are gene symbols or aliases."""
    from hyparena.tools import compounds
    og = opengenes()
    found, hits = set(), set()
    for i in card.pico.intervention:
        for part in compounds.split(i.label):
            c = compounds.lookup(part)
            for t in (c.targets or []) if c else []:
                names = compounds.target_names(t)
                syms = {n for n in names if re.fullmatch(r"[a-z][a-z0-9\-]{1,9}", n)}
                found |= syms
                hits |= {og[n]["symbol"] for n in syms if n in og and og[n]["symbol"].lower() == n}
    for cl in card.claims:
        for ent in (cl.subject, cl.object):
            lab = (ent.label or "").strip()
            # official symbols only: aliases collide with metabolite abbreviations ("NAD" is an alias of a gene)
            if re.fullmatch(r"[A-Z][A-Z0-9\-]{1,9}", lab) and lab.lower() in og and og[lab.lower()]["symbol"] == lab:
                found.add(lab.lower())
                hits.add(lab)
    return found, hits


def genetic_support(card: HypothesisCard) -> tuple[Optional[str], list[str]]:
    found, hits = target_genes(card)
    if not found:
        return None, []
    og = {v["symbol"]: v for v in opengenes().values()}
    if any(og[s]["human"] for s in hits):
        return "human_genetic", sorted(hits)
    return ("aging_gene" if hits else "none"), sorted(hits)

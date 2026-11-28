"""Two indicators from public data, no model calls (specs/scoring/trend-genetics-2026-11-06.yaml):

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
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
STOP = {"with", "from", "that", "this", "plus", "versus", "group", "program", "programme", "intervention", "therapy",
        "treatment", "training", "based", "placebo", "control", "older", "adults", "elderly", "daily", "dose", "oral",
        "supplementation", "supplement", "standard", "usual", "care", "patch", "transdermal", "topical", "pulsating",
        "pulsed", "low-dose", "high-dose", "short-term", "long-term", "chronic", "acute", "naked", "plasmid"}
BROAD_UMBRELLA_TERMS = {
    "electric field", "electric fields", "direct current", "electrical stimulation", "magnetic stimulation",
    "light therapy", "photobiomodulation", "ultrasound", "exercise", "resistance exercise", "aerobic exercise",
    "physical activity", "caloric restriction", "dietary restriction", "fasting", "diet", "sleep", "hypoxia",
    "hyperoxia", "heat therapy", "cold exposure", "vibration", "acupuncture", "breathing",
}
MIN_PUBMED_BASE = 15
MIN_PREPRINT_BASE = 10
MIN_TRIALS_BASE = 6
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


def trials_count_industry(term: str, lo: str, hi: str) -> int:
    k = f"ct_ind|{term}|{lo}|{hi}"
    c = _cache()
    if k not in c:
        params = {
            "query.intr": term,
            "query.term": f"AREA[StartDate]RANGE[{lo},{hi}] AND AREA[LeadSponsorClass]INDUSTRY",
            "countTotal": "true",
            "pageSize": 1,
            "format": "json",
        }
        for attempt in range(4):
            try:
                r = httpx.get(CTGOV, params=params, timeout=30)
                if r.status_code == 400:
                    c[k] = -1
                    break
                r.raise_for_status()
                c[k] = int(r.json().get("totalCount", 0))
                break
            except (httpx.HTTPError, ValueError):
                if attempt == 3:
                    c[k] = -1
                    break
                time.sleep(2 ** attempt)
        _save()
    return c[k]


def epmc_preprint_count(query_expr: str, lo: str, hi: str) -> int:
    """Count EuropePMC preprints (`SRC:PPR`) in `[lo, hi]` by `FIRST_PDATE`; returns `-1` on error."""
    k = f"epmc_ppr|{query_expr}|{lo}|{hi}"
    c = _cache()
    if k not in c:
        q = f"({query_expr}) AND SRC:PPR AND FIRST_PDATE:[{lo} TO {hi}]" if query_expr else f"SRC:PPR AND FIRST_PDATE:[{lo} TO {hi}]"
        params = {"query": q, "resultType": "lite", "pageSize": 1, "format": "json"}
        for attempt in range(4):
            try:
                r = httpx.get(EPMC, params=params, timeout=30)
                if r.status_code >= 400:
                    c[k] = -1
                    break
                c[k] = int(((r.json() or {}).get("hitCount")) or 0)
                break
            except (httpx.HTTPError, ValueError, KeyError):
                if attempt == 3:
                    c[k] = -1
                    break
                time.sleep(2 ** attempt)
        _save()
    return c[k]


def clean_label(label: str) -> str:
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", label or "")
    s = re.split(r"[:;]", s)[0]
    return " ".join(re.sub(r"[^\w\s\-+/]", " ", s).split()).strip()


def parenthetical_aliases(label: str) -> list[str]:
    out: list[str] = []
    for raw in re.findall(r"\(([^)]{2,40})\)", label or ""):
        cl = " ".join(re.sub(r"[^\w\s\-+/]", " ", raw).split()).strip()
        if cl and cl.lower() not in STOP and len(cl.split()) <= 4:
            out.append(cl)
    return out


def words(label: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", label) if w.lower() not in STOP and not w.isdigit()]


def is_broad_umbrella(term: str) -> bool:
    t = " ".join((term or "").lower().split())
    if not t:
        return True
    if t in BROAD_UMBRELLA_TERMS:
        return True
    ws = words(t)
    return bool(ws) and " ".join(w.lower() for w in ws) in BROAD_UMBRELLA_TERMS


def _context_keywords(card: HypothesisCard) -> list[str]:
    """Extract 1-3 specific organ/condition/target keywords to anchor broad or rare intervention labels."""
    cands: list[str] = []
    if isinstance(card.topic, dict) and card.topic.get("label"):
        cands.append(clean_label(str(card.topic["label"])))
    cond = clean_label(card.pico.population.condition or "")
    if cond and cond.lower() not in ("unknown", "healthy", "aging", "ageing"):
        cands.append(cond)
    out_cl = card.outcome_claim
    if out_cl is not None:
        cands.append(clean_label(out_cl.object.label))
    kws: list[str] = []
    generic_ctx = {"function", "score", "rate", "level", "levels", "index", "change", "time", "human", "humans", "mice", "mouse", "aging", "ageing", "disease", "disorder", "syndrome"}
    for c in cands:
        ws = [w for w in words(c) if w.lower() not in generic_ctx and len(w) >= 4]
        if ws:
            phrase = " ".join(ws[:2])
            if phrase.lower() not in {x.lower() for x in kws}:
                kws.append(phrase)
    return kws[:2]


def _target_entities(card: HypothesisCard) -> list[str]:
    """Extract molecular/channel/pathway target names from engagement/pathway claims."""
    out: list[str] = []
    seen: set[str] = set()
    intr_keys = {clean_label(i.label).lower() for i in card.pico.intervention if i.label}
    for cl in card.claims:
        if cl.link in ("engagement", "pathway", "step") or cl.role == "mechanism":
            for ent in (cl.object, cl.subject):
                lab = clean_label(ent.label)
                if not lab or lab.lower() in intr_keys:
                    continue
                ws = words(lab)
                if 1 <= len(ws) <= 3 and not is_broad_umbrella(lab):
                    key = " ".join(ws).lower()
                    if key not in seen and key not in {"intervention", "placebo", "aging", "ageing"}:
                        seen.add(key)
                        out.append(" ".join(ws))
    return out[:3]


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


def attention_queries(card: HypothesisCard) -> list[tuple[str, str, str]]:
    """Build ordered `(pubmed_query, epmc_query, ctgov_term)` candidates for `Method v4.2`
    `attention_momentum`:
      1. Specific intervention label / parenthetical code (anchored by disease/tissue context if broad umbrella);
      2. Mechanism target entity + clinical/organ context (`target AND context`) when proprietary codes are too rare.
    Never emits an unanchored broad physical umbrella (`BROAD_UMBRELLA_TERMS`).
    """
    ctx = _context_keywords(card)
    ctx_pm = ("(" + " OR ".join(f'"{k}"[tiab]' for k in ctx) + ")") if ctx else ""
    ctx_ep = ("(" + " OR ".join(f'"{k}"' for k in ctx) + ")") if ctx else ""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def _add(pm_q: str, ep_q: str, ct_t: str) -> None:
        if pm_q and pm_q not in seen:
            seen.add(pm_q)
            out.append((pm_q, ep_q, ct_t))

    for intr in card.pico.intervention[:2]:
        raw_lab = intr.label or ""
        candidates = [clean_label(raw_lab), *parenthetical_aliases(raw_lab)]
        for cand in candidates:
            if not cand:
                continue
            ws = words(cand)
            core = " ".join(ws[:4]) if ws else cand
            if not core:
                continue
            broad = is_broad_umbrella(cand) or is_broad_umbrella(core)
            if broad:
                if ctx_pm:
                    _add(f'"{core}"[tiab] AND {ctx_pm}', f'"{core}" AND {ctx_ep}', f"{core} {ctx[0]}")
                continue
            if len(cand.split()) <= 4:
                _add(f'"{cand}"[tiab]', f'"{cand}"', cand)
            if core.lower() != cand.lower() and 1 <= len(ws) <= 3 and not is_broad_umbrella(core):
                _add(f'"{core}"[tiab]', f'"{core}"', core)

    # Fallback: target entity + condition/organ context
    for tgt in _target_entities(card):
        if ctx_pm:
            _add(f'"{tgt}"[tiab] AND {ctx_pm}', f'"{tgt}" AND {ctx_ep}', f"{tgt} {ctx[0]}")
        elif len(tgt.split()) >= 2 or re.fullmatch(r"[A-Z0-9\-]{3,10}", tgt):
            _add(f'"{tgt}"[tiab]', f'"{tgt}"', tgt)

    return out


def trend_pubmed(card: HypothesisCard, as_of: str) -> tuple[Optional[float], str]:
    (a0, a1), (b0, b1) = _windows(as_of)
    NA, NB = pubmed_count("all[sb]", a0, a1), pubmed_count("all[sb]", b0, b1)
    for q in terms(card):
        a, b = pubmed_count(q, a0, a1), pubmed_count(q, b0, b1)
        if a + b >= 5:
            return round(math.log((a + 1) / (b + 1)) - math.log(NA / NB), 4), q
    return None, ""


def attention_momentum(card: HypothesisCard, as_of: str, *, include_preprints: bool = True) -> tuple[Optional[float], dict]:
    """Method v4.2 composite pre-cutoff scientific & translational attention momentum (`[T-6y, T-3y)` -> `[T-3y, T)`):
      - Context-anchored query selection (`attention_queries`), blocking generic umbrella terms;
      - PubMed growth (`a + b >= MIN_PUBMED_BASE = 15`), discounted when `Review[pt]` share exceeds 50%;
      - EuropePMC preprint growth (`SRC:PPR`, `p_a + p_b >= 10`);
      - ClinicalTrials.gov start growth + industry-sponsor share (`ct_a + ct_b >= 6`).
    Returns `(score_or_None, diagnostic_dict)`.
    """
    if not as_of:
        return None, {"reason": "missing_as_of"}
    (a0, a1), (b0, b1) = _windows(as_of)
    cands = attention_queries(card)
    if not cands:
        return None, {"reason": "no_anchored_query"}

    NA, NB = pubmed_count("all[sb]", a0, a1), pubmed_count("all[sb]", b0, b1)
    chosen: Optional[tuple[str, str, str, int, int]] = None
    for pm_q, ep_q, ct_t in cands:
        a, b = pubmed_count(pm_q, a0, a1), pubmed_count(pm_q, b0, b1)
        if a + b >= MIN_PUBMED_BASE:
            chosen = (pm_q, ep_q, ct_t, a, b)
            break

    g_pm: Optional[float] = None
    rev_share: Optional[float] = None
    rev_discount = 1.0
    pm_query = ""
    ep_q_sel, ct_t_sel = cands[0][1], cands[0][2]
    pm_counts = (0, 0)
    if chosen is not None:
        pm_query, ep_q_sel, ct_t_sel, a, b = chosen
        pm_counts = (a, b)
        raw_pm = math.log((a + 1) / (b + 1)) - math.log(NA / NB)
        a_rev = pubmed_count(f"({pm_query}) AND Review[pt]", a0, a1)
        rev_share = round(a_rev / max(a, 1), 3)
        if rev_share > 0.50 and raw_pm > 0:
            rev_discount = round(max(0.25, 1.0 - (rev_share - 0.50)), 3)
            g_pm = round(raw_pm * rev_discount, 4)
        else:
            g_pm = round(raw_pm, 4)

    g_ppr: Optional[float] = None
    ppr_counts = (0, 0)
    if include_preprints and ep_q_sel:
        ppr_A = epmc_preprint_count("", a0, a1)
        ppr_B = epmc_preprint_count("", b0, b1)
        pa = epmc_preprint_count(ep_q_sel, a0, a1)
        pb = epmc_preprint_count(ep_q_sel, b0, b1)
        if pa >= 0 and pb >= 0 and ppr_A > 0 and ppr_B > 0 and (pa + pb) >= MIN_PREPRINT_BASE:
            ppr_counts = (pa, pb)
            g_ppr = round(math.log((pa + 1) / (pb + 1)) - math.log((ppr_A + 1) / (ppr_B + 1)), 4)

    g_ct: Optional[float] = None
    ct_counts = (0, 0)
    ind_share: Optional[float] = None
    if ct_t_sel and len(ct_t_sel.split()) <= 6:
        ca, cb = trials_count(ct_t_sel, a0, a1), trials_count(ct_t_sel, b0, b1)
        if ca >= 0 and cb >= 0 and (ca + cb) >= MIN_TRIALS_BASE:
            ct_counts = (ca, cb)
            c_ind = trials_count_industry(ct_t_sel, a0, a1)
            ind_s = (c_ind / max(ca, 1)) if (c_ind >= 0 and ca > 0) else 0.0
            ind_share = round(ind_s, 3)
            g_ct = round(math.log((ca + 1) / (cb + 1)) + 0.25 * ind_s, 4)

    parts: list[tuple[float, float]] = []
    if g_pm is not None:
        parts.append((0.60, g_pm))
    if g_ppr is not None:
        parts.append((0.20, g_ppr))
    if g_ct is not None:
        parts.append((0.20, g_ct))

    if not parts:
        return None, {
            "reason": "below_min_base",
            "tried_queries": [c[0] for c in cands],
        }
    w_sum = sum(w for w, _ in parts)
    composite = round(sum(w * v for w, v in parts) / w_sum, 4)
    return composite, {
        "score": composite,
        "pubmed_query": pm_query,
        "pubmed_counts": list(pm_counts),
        "pubmed_growth": g_pm,
        "review_share": rev_share,
        "review_discount": rev_discount,
        "preprint_counts": list(ppr_counts),
        "preprint_growth": g_ppr,
        "trials_term": ct_t_sel if g_ct is not None else "",
        "trials_counts": list(ct_counts),
        "trials_growth": g_ct,
        "industry_share": ind_share,
    }


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

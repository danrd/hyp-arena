"""Channel B: technical implementation readiness for non-compound interventions (method v3.13).

For compound interventions, regulatory status comes from ChEMBL and ClinicalTrials.gov up to T.
For non-compound interventions (devices, procedures, gene/cell perturbations, exercise, diet), this module
runs one focused reader call over the pre-cutoff abstracts already retrieved for the hypothesis and requires
a code-verified verbatim quote demonstrating the limiting operation:
  - demonstrated -> 1.0 (reason: impl_demonstrated)
  - conditional  -> 0.5 (reason: impl_conditional)
  - missing      -> 0.0 (reason: impl_missing)
Any supported status whose quote fails verbatim verification is automatically downgraded to missing (0.0).
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
import json
import re
from typing import Optional
from xml.etree.ElementTree import ParseError

import httpx

from hyparena.card.models import ClaimVerification, HypothesisCard
from hyparena.llm.prompts import render
from hyparena.reading.verifier import _norm, parse_records

TEMPLATE_VERSION = "v1"
STATUS_SCORE = {"demonstrated": 1.0, "conditional": 0.5, "missing": 0.0}
STATUS_REASON = {"demonstrated": "impl_demonstrated", "conditional": "impl_conditional", "missing": "impl_missing"}


def is_non_drug(card: HypothesisCard) -> bool:
    """True when the card names interventions and at least one is not a compound (and none are blank/unspecified)."""
    interventions = card.pico.intervention
    if not interventions or any(i.type == "unspecified" or i.label.strip().casefold() in {"", "unknown"} for i in interventions):
        return False
    if any(i.type == "other" for i in interventions):
        return False
    return any(i.type != "compound" for i in interventions)


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    val = parse_records(text)
    if isinstance(val, dict):
        return val
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def validate(value: Optional[dict], supplied: dict[str, dict]) -> dict:
    """Verify implementation_status and require a contiguous verbatim quote for demonstrated/conditional."""
    if not isinstance(value, dict):
        return {
            "limiting_means": "", "limiting_operation": "", "raw_status": "error",
            "verified_status": "missing", "evidence_pmid": "", "evidence_quote": "",
            "quote_ok": False, "issue": "unparsed", "gap": "",
        }
    raw_st = str(value.get("implementation_status") or "missing").strip().lower()
    if raw_st not in STATUS_SCORE:
        raw_st = "missing"
    pm = str(value.get("evidence_pmid") or "").strip().removeprefix("PMID:")
    qt = str(value.get("evidence_quote") or "").strip()
    quote_ok = False
    issue = ""
    if raw_st in ("demonstrated", "conditional"):
        if pm in supplied:
            quote = _norm(qt)
            if quote and any(quote in _norm(supplied[pm].get(field) or "") for field in ("title", "abstract")):
                quote_ok = True
            else:
                issue = "unverified_quote"
        else:
            issue = "invalid_pmid"
        verified = raw_st if quote_ok else "missing"
    else:
        verified = "missing"
    return {
        "limiting_means": str(value.get("limiting_means") or ""),
        "limiting_operation": str(value.get("limiting_operation") or ""),
        "raw_status": raw_st,
        "verified_status": verified,
        "evidence_pmid": pm if quote_ok else "",
        "evidence_quote": qt if quote_ok else "",
        "quote_ok": quote_ok,
        "issue": issue,
        "gap": str(value.get("gap") or ""),
    }


def has_checked_quote(implementation: dict) -> bool:
    """A persisted positive assessment must include its checked PMID and quote."""
    pmid = str(implementation.get("evidence_pmid") or "").strip().removeprefix("PMID:")
    quote = implementation.get("evidence_quote")
    return (
        implementation.get("quote_ok") is True
        and pmid.isascii()
        and pmid.isdecimal()
        and isinstance(quote, str)
        and bool(_norm(quote))
    )


@lru_cache(maxsize=256)
def _pre_cutoff_source(pmid: str, as_of: str) -> dict[str, dict]:
    from hyparena.tools import pubmed

    if pmid not in pubmed.search(f"{pmid}[UID]", retmax=1, as_of=as_of):
        return {}
    return pubmed.fetch([pmid])


def pre_cutoff_sources_batch(pmids: list[str], as_of: str) -> dict[str, dict]:
    """Batch-fetch pre-cutoff PubMed titles/abstracts for a list of PMIDs in 2 E-utility calls (esummary + efetch)."""
    clean = list(dict.fromkeys(str(p).strip().removeprefix("PMID:").strip() for p in pmids if str(p).strip().removeprefix("PMID:").strip().isdigit()))
    if not clean or not as_of:
        return {}
    cutoff = date.fromisoformat(as_of).isoformat()
    from hyparena.tools import pubdates, pubmed

    dates = pubdates.pubdates(clean)
    allowed = [p for p in clean if p in dates and dates[p] <= cutoff]
    return pubmed.fetch(allowed) if allowed else {}


def revalidate_saved(
    implementation: Optional[dict],
    as_of: str,
    experiment_text: str = "",
    n_planned: Optional[int] = None,
    prefetched_sources: Optional[dict[str, dict]] = None,
) -> Optional[dict]:
    """Validate hand-prepared readiness (`v1` or `v2` 3-component) against pre-cutoff PubMed / experiment text."""
    if not isinstance(implementation, dict):
        return None
    if "component_checks" in implementation:
        try:
            cutoff = date.fromisoformat(as_of) if as_of else None
        except (ValueError, TypeError):
            return {**validate_components_v4(implementation, {}, experiment_text=experiment_text, n_planned=n_planned), "issue": "missing_or_invalid_cutoff"}
        pmids: list[str] = []
        for cc in implementation.get("component_checks") or []:
            if isinstance(cc, dict):
                pm = str(cc.get("evidence_pmid") or "").strip().removeprefix("PMID:").strip()
                if pm.isascii() and pm.isdecimal() and pm not in pmids:
                    pmids.append(pm)
        ov_pm = str(implementation.get("evidence_pmid") or "").strip().removeprefix("PMID:").strip()
        if ov_pm.isascii() and ov_pm.isdecimal() and ov_pm not in pmids:
            pmids.append(ov_pm)
        sources: dict[str, dict] = {}
        if pmids:
            if cutoff is None:
                return {**validate_components_v4(implementation, {}, experiment_text=experiment_text, n_planned=n_planned), "issue": "missing_or_invalid_cutoff"}
            if prefetched_sources is not None:
                sources = {pm: prefetched_sources[pm] for pm in pmids if pm in prefetched_sources}
            else:
                try:
                    sources = pre_cutoff_sources_batch(pmids, cutoff.isoformat())
                except (httpx.HTTPError, RuntimeError, ValueError, OSError, ParseError):
                    return {**validate_components_v4(implementation, {}, experiment_text=experiment_text, n_planned=n_planned), "issue": "pubmed_unavailable"}
        return validate_components_v4(implementation, sources, experiment_text=experiment_text, n_planned=n_planned)

    status = str(implementation.get("verified_status") or "missing").strip().lower()
    if status not in ("demonstrated", "conditional"):
        return implementation

    assessment = {**implementation, "implementation_status": status}
    if not has_checked_quote(implementation):
        return {**validate(assessment, {}), "issue": "missing_checked_quote"}
    try:
        cutoff = date.fromisoformat(as_of)
    except (ValueError, TypeError):
        return {**validate(assessment, {}), "issue": "missing_or_invalid_cutoff"}
    pmid = str(implementation["evidence_pmid"]).strip().removeprefix("PMID:")
    try:
        sources = _pre_cutoff_source(pmid, cutoff.isoformat())
    except (httpx.HTTPError, RuntimeError, ValueError, OSError, ParseError):
        return {**validate(assessment, {}), "issue": "pubmed_unavailable"}
    result = validate(assessment, sources)
    if not sources:
        result["issue"] = "source_missing_or_after_cutoff"
    return result


def assess(
    client,
    card: HypothesisCard,
    cvs: list[ClaimVerification],
    abstracts: dict[str, dict],
    experiment_text: str = "",
    *,
    avoid: frozenset[str] = frozenset(),
    family: Optional[str] = None,
    log: Optional[list] = None,
    max_papers: int = 8,
    version: str = TEMPLATE_VERSION,
) -> dict:
    """Run one Channel B readiness check over up to `max_papers` already-retrieved abstracts."""
    pmids: list[str] = []
    for cv in cvs:
        for rec in cv.evidence + cv.counterevidence:
            pm = rec.record_id.removeprefix("PMID:")
            if pm.isdigit() and pm in abstracts and pm not in pmids:
                pmids.append(pm)
    supplied = {pm: abstracts[pm] for pm in pmids[:max_papers]}
    if not supplied and version != "v2":
        return {
            "limiting_means": "; ".join(i.label for i in card.pico.intervention),
            "limiting_operation": "", "raw_status": "missing", "verified_status": "missing",
            "evidence_pmid": "", "evidence_quote": "", "quote_ok": False,
            "issue": "no_abstracts", "gap": "No pre-cutoff abstracts available.",
        }
    if not supplied and version == "v2":
        from hyparena.scoring.v3_extra import resource_tier
        return {
            "resource_tier": resource_tier(card),
            "overall_evidence_status": "insufficient",
            "min_readiness_score": 0.0,
            "mean_readiness_score": 0.0,
            "component_checks": [],
            "external_validity_flags": list(getattr(card.decisive_experiment, "external_validity_flags", None) or []),
            "safety_flags": list(getattr(card.decisive_experiment, "safety_flags", None) or []),
            "tradeoff": "",
            "issue": "no_abstracts",
        }

    chosen_family = family
    if not chosen_family:
        fams = [f for f in getattr(client, "families", lambda: [])() if f not in avoid] if callable(getattr(client, "families", None)) else []
        chosen_family = "deepseek" if "deepseek" in fams else (fams[0] if fams else None)
    if not chosen_family:
        return {
            "limiting_means": "", "limiting_operation": "", "raw_status": "missing",
            "verified_status": "missing", "evidence_pmid": "", "evidence_quote": "",
            "quote_ok": False, "issue": "no_family", "gap": "",
        }

    abs_block = "\n\n".join(
        f"[PMID {pm} ({p.get('year') or ''})]\nTitle: {p.get('title') or ''}\nAbstract: {p.get('abstract') or ''}"
        for pm, p in supplied.items()
    )
    de = card.decisive_experiment
    exp_summary = (
        f"design={de.design}, control={de.control}, endpoint={de.endpoint}, "
        f"duration={de.duration_class}, n={de.n_planned}"
    )
    prompt = render(
        "implementation_readiness",
        version,
        claim=card.claim_plain,
        interventions="; ".join(f"{i.label} (type={i.type})" for i in card.pico.intervention),
        system=de.system,
        exp_summary=exp_summary,
        exp_text=(experiment_text or "")[:1500],
        abstracts_block=abs_block,
    )
    reply = client.call(role="verify_claim", family=chosen_family, prompt=prompt)
    if version == "v2":
        checked_v4 = validate_components_v4(
            _parse_json(reply.text),
            supplied,
            experiment_text=experiment_text,
            n_planned=de.n_planned,
        )
        if log is not None:
            log.append({
                "kind": "llm",
                "template": f"implementation_readiness/{version}",
                "role": "verify_claim",
                "family": chosen_family,
                "overall_evidence_status": checked_v4["overall_evidence_status"],
                "min_readiness_score": checked_v4["min_readiness_score"],
                "tokens_in": getattr(reply, "tokens_in", 0),
                "tokens_out": getattr(reply, "tokens_out", 0),
                "seconds": getattr(reply, "seconds", 0.0),
                "error": getattr(reply, "error", None),
            })
        return checked_v4
    checked = validate(_parse_json(reply.text), supplied)
    if log is not None:
        log.append({
            "kind": "llm",
            "template": f"implementation_readiness/{TEMPLATE_VERSION}",
            "role": "verify_claim",
            "family": chosen_family,
            "verified_status": checked["verified_status"],
            "quote_ok": checked["quote_ok"],
            "issue": checked["issue"],
            "tokens_in": getattr(reply, "tokens_in", 0),
            "tokens_out": getattr(reply, "tokens_out", 0),
            "seconds": getattr(reply, "seconds", 0.0),
            "error": getattr(reply, "error", None),
        })
    return checked


COMPONENT_SCORE_V4 = {
    "confirmed_in_context": 1.0,
    "adjacent_only": 0.5,
    "insufficient": 0.0,
}


SCARCE_HUMAN_ORGAN_TOKENS = (
    "donor heart",
    "donor-heart",
    "donor human heart",
    "explanted heart",
    "explanted diseased heart",
    "perfused human atri",
    "atrial preparation",
    "sinoatrial",
    "neurosurgical",
    "cortical tissue",
    "cortical capillary",
    "postmortem brain",
)

_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}


def _cited_scarce_organ_n(comp_name: str, target_sys: str, quote: str) -> Optional[int]:
    """Extract demonstrated donor/organ sample size from `quote` when `target_sys` is a scarce human organ model."""
    cname = (comp_name or "").lower()
    if cname not in ("population_or_model", "system_or_population_fit"):
        return None
    ts = (target_sys or "").lower()
    if not any(tok in ts for tok in SCARCE_HUMAN_ORGAN_TOKENS):
        return None
    q = quote or ""
    if not q.strip():
        return None
    ns = [int(m) for m in re.findall(r"\bn\s*[=≈~]\s*(\d+)\b", q, re.I) if int(m) > 0]
    for m in re.finditer(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)\s+"
        r"(?:usable\s+|explanted\s+|diseased\s+|donor\s+|perfused\s+|human\s+|right\s+|left\s+){1,5}"
        r"(?:hearts?|atria|preparations?|brains?|donors?)\b",
        q,
        re.I,
    ):
        tok = m.group(1).lower()
        val = int(tok) if tok.isdigit() else _WORD_NUMS.get(tok, 0)
        if val > 0:
            ns.append(val)
    return max(ns) if ns else None


def validate_components_v4(
    value: Optional[dict],
    supplied: dict[str, dict],
    experiment_text: str = "",
    n_planned: Optional[int] = None,
) -> dict:
    """Method v4 component-level readiness validator (`implementation_readiness/v2`).

    Verifies verbatim quotes for each component (`confirmed_in_context` / `adjacent_only`),
    downgrading unverified quotes to `insufficient`, enforces scarce human donor-organ sample-size
    realism (`n_planned <= 3 * cited_n`), and computes `min_readiness_score` (weak-link score).
    """
    if not isinstance(value, dict):
        return {
            "resource_tier": None,
            "overall_evidence_status": "insufficient",
            "min_readiness_score": 0.0,
            "mean_readiness_score": 0.0,
            "component_checks": [],
            "external_validity_flags": [],
            "safety_flags": [],
        }

    norm_exp = _norm(experiment_text or "")

    def _quote_verified(pmid: str, qt: str) -> bool:
        q_norm = _norm(qt or "")
        if not q_norm:
            return False
        pm = str(pmid or "").strip().removeprefix("PMID:").strip()
        if pm and pm in supplied:
            rec = supplied[pm]
            if any(q_norm in _norm(rec.get(f) or "") for f in ("title", "abstract")):
                return True
        if norm_exp and q_norm in norm_exp:
            return True
        return False

    checked_comps: list[dict] = []
    comp_scores: list[float] = []
    for cc in value.get("component_checks") or []:
        if not isinstance(cc, dict):
            continue
        comp_name = str(cc.get("component") or "")
        target_sys = str(cc.get("target_system") or "")
        st = str(cc.get("evidence_status") or "insufficient").strip()
        if st not in ("confirmed_in_context", "adjacent_only", "insufficient", "not_applicable"):
            st = "insufficient"
        pm = str(cc.get("evidence_pmid") or "").strip().removeprefix("PMID:").strip()
        qt = str(cc.get("evidence_quote") or "").strip()
        notes = str(cc.get("notes") or "")
        q_ok = True
        scale_exceeded = False
        if st in ("confirmed_in_context", "adjacent_only"):
            q_ok = _quote_verified(pm, qt)
            if not q_ok:
                st = "insufficient"
            elif n_planned is not None and n_planned > 0:
                cited_n = _cited_scarce_organ_n(comp_name, target_sys, qt)
                if cited_n is not None and n_planned > 3 * cited_n:
                    st = "insufficient"
                    scale_exceeded = True
                    tag = f"[scale_exceeds_cited_3x: planned={n_planned} vs cited={cited_n}]"
                    notes = f"{notes} {tag}".strip()
        if st in COMPONENT_SCORE_V4:
            comp_scores.append(COMPONENT_SCORE_V4[st])
        checked_comps.append(
            {
                "component": comp_name,
                "target_system": target_sys,
                "evidence_status": st,
                "evidence_pmid": pm if q_ok else "",
                "evidence_quote": qt if q_ok else "",
                "quote_ok": q_ok,
                "scale_exceeded": scale_exceeded,
                "notes": notes,
            }
        )

    min_score = round(min(comp_scores), 3) if comp_scores else 0.0
    mean_score = round(sum(comp_scores) / len(comp_scores), 3) if comp_scores else 0.0

    raw_overall = str(value.get("overall_evidence_status") or "insufficient").strip()
    if raw_overall not in ("confirmed_in_context", "adjacent_only", "insufficient", "not_applicable"):
        raw_overall = "insufficient"
    ov_pm = str(value.get("evidence_pmid") or "").strip().removeprefix("PMID:").strip()
    ov_qt = str(value.get("evidence_quote") or "").strip()
    if any(c.get("scale_exceeded") for c in checked_comps):
        raw_overall = "insufficient"
    elif raw_overall in ("confirmed_in_context", "adjacent_only"):
        if not (_quote_verified(ov_pm, ov_qt) or any(c["evidence_status"] in ("confirmed_in_context", "adjacent_only") for c in checked_comps)):
            raw_overall = "insufficient"
        elif raw_overall == "confirmed_in_context" and any(c["evidence_status"] != "confirmed_in_context" for c in checked_comps if c["evidence_status"] != "not_applicable"):
            raw_overall = "adjacent_only"

    tier = value.get("resource_tier")
    if tier not in ("1_in_vitro", "2_animal", "3_human_ex_vivo_or_pilot", "4_clinical_in_vivo"):
        tier = None

    return {
        "resource_tier": tier,
        "overall_evidence_status": raw_overall,
        "min_readiness_score": min_score,
        "mean_readiness_score": mean_score,
        "component_checks": checked_comps,
        "external_validity_flags": [str(x) for x in (value.get("external_validity_flags") or []) if isinstance(x, str)],
        "safety_flags": [str(x) for x in (value.get("safety_flags") or []) if isinstance(x, str)],
        "tradeoff": str(value.get("tradeoff") or ""),
    }

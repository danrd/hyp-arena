"""Additional indicators of a v3 result, computed by code from the card and the saved records (no model calls), for the lower
tiers of the ASPID profiles over the v3 axes (hyparena/scoring/aspid_v3.py; method-v3.md section 13).

Candidates (user, 2026-11-05: compute all of them on the calibration for a rough look, use four first):
- best_design_outcome: the best design among the usable records for the outcome link (ordinal, as the v2 effect ladder);
- independent_outcome: independent sources for the outcome link (count);
- against_share: A / (F + A) over the chain (the share of the weight against; lower is better);
- feasibility: section 9.4, the mean of the applicable scores in [0, 1], with a reserved slot for intervention readiness;
- weakest_level: the level of the weakest link (ordinal);
- human_outcome: any usable record about humans for the outcome link;
- best_effect_outcome: the largest effect class among the outcome link's records for (ordinal; unclear in the middle);
- unverified_links: links without any usable record (count; lower is better);
- momentum: share of the supporting records published in the five years up to T.
"""
from __future__ import annotations

from typing import Optional

from hyparena.scoring import rules_v3 as r3
from hyparena.card.models import ClaimVerification, DecisiveExperiment, HypothesisCard

DESIGN_LADDER = ("none", "cells", "animal", "observational", "review", "non_randomised", "meta_analysis", "rct")
EFFECT_LADDER = ("none", "small", "unclear", "medium", "large")
FIRST_FOUR = ("best_design_outcome", "independent_outcome", "against_share", "feasibility")

SYSTEM_COST = {"data_analysis": 1.0, "cells": 1.0, "yeast": 0.9, "worm": 0.85, "fly": 0.85, "mouse": 0.5, "rat": 0.5, "human": 0.0}
DURATION_COST = {"weeks": 1.0, "months": 2 / 3, "years": 1 / 3, "decades": 0.0}


def _n_score(n: Optional[int]) -> Optional[float]:
    if n is None:
        return None
    return 1.0 if n < 50 else 2 / 3 if n < 200 else 1 / 3 if n < 1000 else 0.0


EX_VIVO_TOKENS = (
    "explant",
    "ex vivo",
    "discarded",
    "surgical donor",
    "organ donor",
    "donor-heart",
    "donor heart",
    "explanted heart",
    "explanted diseased heart",
    "perfused human",
    "atrial preparation",
    "trabecular core",
    "perifus",
    "intact islet",
    "pseudoislet",
    "bronchial brushing",
    "air-liquid",
    "air–liquid",
    "ussing",
    "vastus lateralis sample",
    "low-passage",
    "myoblast",
    "stromal cell",
    "osteoblast",
    "neurosurgical",
    "cortical tissue",
    "capillary-arteriole",
    "capillary–arteriole",
    "eye-bank",
    "eye bank",
    "postmortem",
    "organoid",
    "biopsy culture",
    "acutely isolated",
    "sinoatrial myocyte",
)


def is_human_ex_vivo(card: HypothesisCard, implementation: Optional[dict] = None) -> bool:
    """True when `system == 'human'` refers to ex vivo donor organs, explants, or primary tissue/cell preparations
    rather than an in vivo clinical intervention in living participants.
    """
    e = card.decisive_experiment
    if str(e.system or "").lower() != "human":
        return False
    hay = " ".join(
        [
            e.span or "",
            e.primary_outcome or "",
            " ".join(e.primary_outcomes or []),
        ]
    ).lower()
    if any(tok in hay for tok in EX_VIVO_TOKENS):
        return True
    if isinstance(implementation, dict):
        comp_text = " ".join(
            str(cc.get("target_system") or "")
            for cc in (implementation.get("component_checks") or [])
            if isinstance(cc, dict)
        ).lower()
        if any(tok in comp_text for tok in EX_VIVO_TOKENS):
            return True
    return False


def endpoint_for_experiment(
    endpoint: Optional[str],
    system: Optional[str],
    card: Optional[HypothesisCard] = None,
    implementation: Optional[dict] = None,
) -> Optional[str]:
    """Clinical endpoint levels apply only to in vivo studies in living humans (v3.13 / v4.0)."""
    if endpoint in ("patient_reported", "function", "clinical_event"):
        if system and system != "human":
            return "biomarker"
        if card is not None and is_human_ex_vivo(card, implementation):
            return "biomarker"
    return endpoint


def _chembl_component(label: str, compounds_mod) -> tuple[Optional[float], Optional[str], str]:
    """(phase_score, entity_id, reason) from ChEMBL/PubChem alone."""
    try:
        match = compounds_mod.lookup(label, raise_on_error=True)
    except compounds_mod.LookupError_:
        return None, None, "lookup_failed"
    if match is None:
        return None, None, "unresolved"
    given = compounds_mod.key(compounds_mod.resolve_alias(label))
    if given not in {compounds_mod.key(name) for name in [match.name, *match.synonyms]}:
        return None, None, "identity_unverified"
    if not match.chembl or match.max_phase is None:
        return None, None, "phase_unknown"
    ph = match.max_phase
    score = 1.0 if ph >= 4 else 0.5 if ph >= 1 else 0.0
    return score, match.chembl, ("approved" if ph >= 4 else "clinical" if ph >= 1 else "preclinical")


def readiness_assessment(card: HypothesisCard, as_of: str = "",
                         implementation: Optional[dict] = None) -> tuple[Optional[float], str]:
    """Use documented regulatory status. Intervention type alone earns no readiness.
    When `as_of` is given and ChEMBL has no verified phase for a compound, fall back to
    ClinicalTrials.gov trials submitted on or before `as_of` (v3.13).
    For non-compound interventions, when a code-verified Channel B `implementation` assessment
    (`verified_status` in demonstrated/conditional/missing) is supplied, map it to 1.0 / 0.5 / 0.0 (v3.13)."""
    from hyparena.reading import implementation as impl_mod
    from hyparena.tools import clinicaltrials, compounds

    interventions = card.pico.intervention
    if not interventions or any(i.type == "unspecified" or i.label.strip().casefold() in {"", "unknown"}
                                for i in interventions):
        return None, "unspecified"
    drugs = [i for i in interventions if i.type == "compound"]
    if any(i.type == "other" for i in interventions):
        return None, "unclassified"
    if len(drugs) != len(interventions):
        if isinstance(implementation, dict):
            if "min_readiness_score" in implementation and "overall_evidence_status" in implementation:
                ov = str(implementation.get("overall_evidence_status") or "insufficient")
                sc = float(implementation.get("min_readiness_score") or 0.0)
                return max(0.0, min(1.0, sc)), f"v4_{ov}"
            st = str(implementation.get("verified_status") or "").strip().lower()
            if st in ("demonstrated", "conditional") and not impl_mod.has_checked_quote(implementation):
                st = "missing"
            if st in impl_mod.STATUS_SCORE:
                return impl_mod.STATUS_SCORE[st], impl_mod.STATUS_REASON[st]
        return None, "implementation_unverified"
    components = [compounds.split(drug.label) for drug in drugs]
    if not all(components):
        return None, "unresolved"
    labels = list(dict.fromkeys(part for parts in components for part in parts))

    scores: list[float] = []
    entity_ids: set[str] = set()
    used_ct = False
    for label in labels:
        score, ent_id, reason = _chembl_component(label, compounds)
        if score is not None and ent_id is not None:
            scores.append(score)
            entity_ids.add(ent_id)
            continue
        if as_of:
            ct = clinicaltrials.compound_phase(label, as_of)
            if ct and ct.get("matched"):
                ph = ct.get("max_phase")
                ct_score = (1.0 if ph >= 4 else 0.5 if ph >= 1 else 0.0) if ph is not None else 0.5
                scores.append(ct_score)
                entity_ids.add(f"CT:{clinicaltrials._norm_key(label)}")
                used_ct = True
                continue
        if isinstance(implementation, dict) and "min_readiness_score" in implementation and implementation.get("component_checks"):
            comp_min = max(0.0, min(1.0, float(implementation["min_readiness_score"] or 0.0)))
            return comp_min, f"v4_{implementation.get('overall_evidence_status') or 'literature_components'}"
        return None, reason

    min_score = min(scores)
    if isinstance(implementation, dict) and "min_readiness_score" in implementation and implementation.get("component_checks"):
        comp_min = max(0.0, min(1.0, float(implementation["min_readiness_score"] or 0.0)))
        if comp_min < min_score:
            return comp_min, f"v4_{implementation.get('overall_evidence_status') or 'component_capped'}"
    if min_score >= 1.0 and len(entity_ids) > 1:
        return 0.5, ("ct_combination_unverified" if used_ct else "combination_unverified")
    prefix = "ct_" if used_ct else ""
    if min_score >= 1.0:
        return 1.0, f"{prefix}approved"
    if min_score >= 0.5:
        return 0.5, f"{prefix}clinical"
    return 0.0, f"{prefix}preclinical"


def readiness(card: HypothesisCard, as_of: str = "", implementation: Optional[dict] = None) -> Optional[float]:
    if not as_of and implementation is None:
        return readiness_assessment(card)[0]
    try:
        return readiness_assessment(card, as_of, implementation)[0]
    except TypeError:
        try:
            return readiness_assessment(card, as_of)[0]
        except TypeError:
            return readiness_assessment(card)[0]


def _call_readiness(card: HypothesisCard, as_of: str = "", implementation: Optional[dict] = None) -> Optional[float]:
    if not as_of and implementation is None:
        return readiness(card)
    try:
        return readiness(card, as_of, implementation)
    except TypeError:
        try:
            return readiness(card, as_of)
        except TypeError:
            return readiness(card)


def claim_is_human(card: HypothesisCard, source_text: str = "") -> bool:
    """True when the card's claimed target population, outcome claim, or opening thesis in `source_text` is human."""
    pop = card.pico.population
    tax = (pop.taxon or "").lower()
    lab = f"{pop.label or ''} {pop.condition or ''} {card.claim_plain or ''}".lower()
    if "9606" in tax or "homo sapiens" in tax:
        return True
    human_phrases = ("older adult", "older people", "older women", "older men", "adults aged", "patients", "human")
    if any(w in lab for w in human_phrases):
        return True
    head = (source_text or "")[:400].lower()
    if any(w in head for w in ("older adult", "older people", "older women", "older men", "adults aged", "in patients with")):
        return True
    return any(r3.human_claim(c) for c in card.claims if c.role == "outcome" or c.link == "outcome")


SAFETY_MONITOR_TOKENS = ("titrat", "run-in", "tolerab", "monitor", "ecg", "safety")


def collect_safety_flags(card: HypothesisCard, implementation: Optional[dict] = None) -> set[str]:
    flags = set(getattr(card.decisive_experiment, "safety_flags", None) or [])
    if isinstance(implementation, dict):
        flags |= {str(x) for x in (implementation.get("safety_flags") or []) if str(x).strip()}
    return flags


def safety_readiness_cap(
    card: HypothesisCard,
    readiness_score: Optional[float],
    readiness_reason: str,
    implementation: Optional[dict] = None,
    experiment_text: str = "",
) -> tuple[Optional[float], str]:
    """In vivo living-human safety caps on readiness (`Method v4.1`)."""
    e = card.decisive_experiment
    if str(e.system or "").lower() != "human" or is_human_ex_vivo(card, implementation):
        return readiness_score, readiness_reason
    s_flags = collect_safety_flags(card, implementation)
    if "unjustified_risk_in_healthy_older" in s_flags:
        return 0.0, "safety_unjustified_risk"
    if "on_target_pleiotropy" in s_flags:
        span_l = (experiment_text or e.span or "").lower()
        if not any(tok in span_l for tok in SAFETY_MONITOR_TOKENS):
            return 0.0, "safety_unmonitored_pleiotropy"
        cur = readiness_score if readiness_score is not None else 0.0
        if cur > 0.5:
            return 0.5, "safety_pleiotropy_capped"
    return readiness_score, readiness_reason


def sample_size_score(experiment: DecisiveExperiment) -> Optional[float]:
    """Reserve the sample-size component for a stated empirical system."""
    n = experiment.n_planned
    if experiment.system in SYSTEM_COST and experiment.system != "data_analysis" and (n is None or n <= 0):
        return 0.0
    return _n_score(n)


def feasibility(
    card: HypothesisCard,
    as_of: str = "",
    implementation: Optional[dict] = None,
    *,
    claim_aligned: bool = False,
    experiment_text: str = "",
) -> float:
    e = card.decisive_experiment
    sys_score = (
        0.0
        if (claim_aligned and claim_is_human(card, experiment_text) and e.system in SYSTEM_COST)
        else SYSTEM_COST.get(e.system)
    )
    parts = [sys_score, DURATION_COST.get(e.duration_class), sample_size_score(e)]
    known = [p for p in parts if p is not None]
    r_score = _call_readiness(card, as_of, implementation)
    if claim_aligned:
        r_score, _ = safety_readiness_cap(card, r_score, "", implementation, experiment_text)
    # Missing readiness retains its place so withholding it cannot raise feasibility.
    return round((sum(known) + (r_score or 0.0)) / (len(known) + 1), 3)


def feasibility_breakdown(
    card: HypothesisCard,
    as_of: str = "",
    implementation: Optional[dict] = None,
    *,
    claim_aligned: bool = False,
    experiment_text: str = "",
) -> dict:
    """Component-level breakdown of feasibility(card) for display in the evaluation tab."""
    e = card.decisive_experiment
    is_hum = claim_is_human(card, experiment_text)
    human_claim_override = bool(claim_aligned and is_hum and e.system in SYSTEM_COST and e.system != "human")
    sys_score = 0.0 if (claim_aligned and is_hum and e.system in SYSTEM_COST) else SYSTEM_COST.get(e.system)
    dur_score = DURATION_COST.get(e.duration_class)
    n_score = sample_size_score(e)
    n_missing_reserved = (
        e.system in SYSTEM_COST and e.system != "data_analysis"
        and (e.n_planned is None or e.n_planned <= 0)
    )
    try:
        if as_of or implementation is not None:
            readiness_score, readiness_reason = readiness_assessment(card, as_of, implementation)
        else:
            readiness_score, readiness_reason = readiness_assessment(card)
    except TypeError:
        readiness_score, readiness_reason = readiness_assessment(card)
    if claim_aligned:
        readiness_score, readiness_reason = safety_readiness_cap(
            card, readiness_score, readiness_reason, implementation, experiment_text
        )
    known = [p for p in (sys_score, dur_score, n_score) if p is not None]
    denom = len(known) + 1
    total = round((sum(known) + (readiness_score or 0.0)) / denom, 3)
    readiness_part = {
        "key": "readiness",
        "value": readiness_reason,
        "score": round(readiness_score, 3) if readiness_score is not None else 0.0,
        "known": readiness_score is not None,
        "in_denominator": True,
        "reason": readiness_reason,
    }
    if isinstance(implementation, dict) and readiness_reason.startswith("impl_"):
        if readiness_reason in ("impl_demonstrated", "impl_conditional"):
            readiness_part["evidence_pmid"] = implementation["evidence_pmid"]
        if implementation.get("issue"):
            readiness_part["issue"] = implementation["issue"]
        if implementation.get("gap"):
            readiness_part["gap"] = implementation["gap"]
    elif isinstance(implementation, dict) and readiness_reason.startswith("v4_"):
        readiness_part["resource_tier"] = implementation.get("resource_tier") or resource_tier(card)
        readiness_part["overall_evidence_status"] = implementation.get("overall_evidence_status")
        comps = implementation.get("component_checks") or []
        if comps:
            readiness_part["component_checks"] = comps
            pmids = [str(c.get("evidence_pmid") or "") for c in comps if isinstance(c, dict) and c.get("evidence_pmid")]
            if pmids:
                readiness_part["evidence_pmid"] = ", ".join(dict.fromkeys(pmids))
        if implementation.get("issue"):
            readiness_part["issue"] = implementation["issue"]
    sys_part = {
        "key": "system",
        "value": e.system,
        "score": round(sys_score, 3) if sys_score is not None else None,
        "in_denominator": sys_score is not None,
    }
    if human_claim_override:
        sys_part["reason"] = "human_claim_aligned"
    parts = [
        sys_part,
        {
            "key": "duration",
            "value": e.duration_class,
            "score": round(dur_score, 3) if dur_score is not None else None,
            "in_denominator": dur_score is not None,
        },
        {
            "key": "sample_size",
            "value": e.n_planned,
            "score": round(n_score, 3) if n_score is not None else None,
            "in_denominator": n_score is not None,
            "reason": "missing_reserved" if n_missing_reserved else ("not_applicable" if n_score is None else "stated"),
        },
        readiness_part,
    ]
    return {"score": total, "denominator": denom, "parts": parts}


def extras(card: HypothesisCard, ver_claims: list[ClaimVerification], v3: dict, as_of: str = "",
           variant: str = "v3", implementation: Optional[dict] = None,
           *, claim_aligned: bool = False, experiment_text: str = "") -> dict:
    """All candidate indicators of one hypothesis; `v3` is its V3Result.as_dict()."""
    by_id = {cv.id: cv for cv in ver_claims}
    links = r3.chain(card)
    outs, primary = r3.outcome_group(card, links)
    out_claims = [primary] if primary is not None else outs
    out_recs = [(r, c) for c in out_claims for r in (by_id.get(c.id).evidence if by_id.get(c.id) else [])
                if r3.record_weight(r, c, False, variant) > 0]
    designs = [r3.record_design(r) for r, _ in out_recs]
    best_design = max(designs, key=lambda d: DESIGN_LADDER.index(d) if d in DESIGN_LADDER else 0, default="none")
    if best_design not in DESIGN_LADDER:
        best_design = "none"
    effects = [r.effect_class for r, _ in out_recs if r.effect_class in EFFECT_LADDER]
    F = sum(v3["weights"].get(c.id, [0, 0])[0] for c in links)
    A = sum(v3["weights"].get(c.id, [0, 0])[1] for c in links)
    lw = lambda lv_: r3._lw(lv_, variant)
    levels = [v3["links"].get(c.id, "unverified") for c in links]
    support = [r for c in links for r in (by_id.get(c.id).evidence if by_id.get(c.id) else [])
               if r3.record_weight(r, c, False, variant) > 0]
    years = [int(r.retrieved_at[:4]) for r in support if (r.retrieved_at or "")[:4].isdigit()]
    t_year = int(as_of[:4]) if as_of[:4].isdigit() else None
    return {
        "best_design_outcome": best_design,
        "independent_outcome": r3._independent([r for r, _ in out_recs]),
        "against_share": round(A / (F + A), 3) if F + A > 0 else 0.0,
        "feasibility": feasibility(card, as_of, implementation, claim_aligned=claim_aligned, experiment_text=experiment_text),
        "weakest_level": min(levels, key=lw) if levels else "unverified",
        "human_outcome": any(r3.species_key(r.species) == "human" or r3.human_claim(c) and r3.context_level(r) == "exact"
                             for r, c in out_recs),
        "best_effect_outcome": max(effects, key=EFFECT_LADDER.index, default="none"),
        "unverified_links": sum(1 for x in levels if x == "unverified"),
        "momentum": round(sum(1 for y in years if t_year and y >= t_year - 4) / len(years), 3) if years and t_year else None,
    }


def resource_tier(card: HypothesisCard, implementation: Optional[dict] = None) -> Optional[str]:
    """Separate resource class (Tier 1..4) from within-tier execution readiness
    (evaluation-calibration-2026-11-25.md section 3).
    """
    if isinstance(implementation, dict):
        saved_tier = implementation.get("resource_tier")
        if saved_tier in ("1_in_vitro", "2_animal", "3_human_ex_vivo_or_pilot", "4_clinical_in_vivo"):
            return saved_tier
    e = card.decisive_experiment
    sys_name = str(e.system or "unknown").lower()
    if sys_name in ("cells", "yeast", "data_analysis"):
        return "1_in_vitro"
    if sys_name in ("mouse", "rat", "worm", "fly"):
        return "2_animal"
    if sys_name == "human":
        if e.design == "pilot" or is_human_ex_vivo(card, implementation):
            return "3_human_ex_vivo_or_pilot"
        return "4_clinical_in_vivo"
    return None


def feasibility_diagnostic(
    card: HypothesisCard,
    as_of: str = "",
    implementation: Optional[dict] = None,
    *,
    offline_readiness: Optional[tuple[Optional[float], str]] = None,
) -> dict:
    """Diagnostic split of feasibility into `resource_tier` (cost class) and `execution_readiness`
    (within-class readiness, duration, precision/unit adequacy cues, and safety/external-validity flags).
    Does not alter feasibility() or feasibility_breakdown().
    """
    e = card.decisive_experiment
    tier = resource_tier(card, implementation)
    if offline_readiness is not None:
        r_score, r_reason = offline_readiness
    else:
        r_score, r_reason = readiness_assessment(card, as_of, implementation)
    dur_score = DURATION_COST.get(e.duration_class)
    n_score = sample_size_score(e)
    return {
        "resource_tier": tier,
        "execution_readiness": {
            "readiness_score": round(r_score, 3) if r_score is not None else None,
            "readiness_reason": r_reason,
            "duration_class": e.duration_class,
            "duration_score": round(dur_score, 3) if dur_score is not None else None,
            "n_planned": e.n_planned,
            "n_per_contrast": getattr(e, "n_per_contrast", None),
            "n_score": round(n_score, 3) if n_score is not None else None,
            "experimental_unit": getattr(e, "experimental_unit", ""),
            "precision_basis_present": bool((getattr(e, "precision_basis", "") or "").strip()),
            "tested_scope": getattr(e, "tested_scope", None),
            "endpoint_best_class": getattr(e, "endpoint_best_class", None),
        },
        "external_validity_flags": list(getattr(e, "external_validity_flags", None) or []),
        "safety_flags": list(getattr(e, "safety_flags", None) or []),
    }

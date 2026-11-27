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


def endpoint_for_experiment(endpoint: Optional[str], system: Optional[str]) -> Optional[str]:
    """Clinical endpoint levels apply only when the stated experiment is in humans (v3.13)."""
    if system and system != "human" and endpoint in ("patient_reported", "function", "clinical_event"):
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


def sample_size_score(experiment: DecisiveExperiment) -> Optional[float]:
    """Reserve the sample-size component for a stated empirical system."""
    n = experiment.n_planned
    if experiment.system in SYSTEM_COST and experiment.system != "data_analysis" and (n is None or n <= 0):
        return 0.0
    return _n_score(n)


def feasibility(card: HypothesisCard, as_of: str = "", implementation: Optional[dict] = None) -> float:
    e = card.decisive_experiment
    parts = [SYSTEM_COST.get(e.system), DURATION_COST.get(e.duration_class), sample_size_score(e)]
    known = [p for p in parts if p is not None]
    # Missing readiness retains its place so withholding it cannot raise feasibility.
    return round((sum(known) + (_call_readiness(card, as_of, implementation) or 0.0)) / (len(known) + 1), 3)


def feasibility_breakdown(card: HypothesisCard, as_of: str = "", implementation: Optional[dict] = None) -> dict:
    """Component-level breakdown of feasibility(card) for display in the evaluation tab."""
    e = card.decisive_experiment
    sys_score = SYSTEM_COST.get(e.system)
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
    parts = [
        {
            "key": "system",
            "value": e.system,
            "score": round(sys_score, 3) if sys_score is not None else None,
            "in_denominator": sys_score is not None,
        },
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
           variant: str = "v3", implementation: Optional[dict] = None) -> dict:
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
        "feasibility": feasibility(card, as_of, implementation),
        "weakest_level": min(levels, key=lw) if levels else "unverified",
        "human_outcome": any(r3.species_key(r.species) == "human" or r3.human_claim(c) and r3.context_level(r) == "exact"
                             for r, c in out_recs),
        "best_effect_outcome": max(effects, key=EFFECT_LADDER.index, default="none"),
        "unverified_links": sum(1 for x in levels if x == "unverified"),
        "momentum": round(sum(1 for y in years if t_year and y >= t_year - 4) / len(years), 3) if years and t_year else None,
    }


def resource_tier(card: HypothesisCard) -> Optional[str]:
    """Separate resource class (Tier 1..4) from within-tier execution readiness
    (evaluation-calibration-2026-11-25.md section 3).
    """
    e = card.decisive_experiment
    sys_name = str(e.system or "unknown").lower()
    span = (e.span or "").lower()
    if sys_name in ("cells", "yeast", "data_analysis"):
        return "1_in_vitro"
    if sys_name in ("mouse", "rat", "worm", "fly"):
        return "2_animal"
    if sys_name == "human":
        if e.design == "pilot" or any(tok in span for tok in ("explant", "ex vivo", "discarded", "surgical donor", "biopsy culture")):
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
    tier = resource_tier(card)
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

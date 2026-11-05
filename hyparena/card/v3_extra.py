"""Additional indicators of a v3 result, computed by code from the card and the saved records (no model calls), for the lower
tiers of the ASPID profiles over the v3 axes (hyparena/card/aspid_v3.py; method-v3.md section 13).

Candidates (user, 2026-11-05: compute all of them on the calibration for a rough look, use four first):
- best_design_outcome: the best design among the usable records for the outcome link (ordinal, as the v2 effect ladder);
- independent_outcome: independent sources for the outcome link (count);
- against_share: A / (F + A) over the chain (the share of the weight against; lower is better);
- feasibility: section 9.4, the mean of known parts in [0, 1] (system, duration, planned n, readiness of the intervention);
- weakest_level: the level of the weakest link (ordinal);
- human_outcome: any usable record about humans for the outcome link;
- best_effect_outcome: the largest effect class among the outcome link's records for (ordinal; unclear in the middle);
- unverified_links: links without any usable record (count; lower is better);
- momentum: share of the supporting records published in the five years up to T.
"""
from __future__ import annotations

from typing import Optional

from hyparena.card import rules_v3 as r3
from hyparena.card.models import ClaimVerification, HypothesisCard

DESIGN_LADDER = ("none", "cells", "animal", "observational", "review", "non_randomised", "meta_analysis", "rct")
EFFECT_LADDER = ("none", "small", "unclear", "medium", "large")
FIRST_FOUR = ("best_design_outcome", "independent_outcome", "against_share", "feasibility")

SYSTEM_COST = {"data_analysis": 1.0, "cells": 1.0, "yeast": 0.9, "worm": 0.85, "fly": 0.85, "mouse": 0.5, "rat": 0.5, "human": 0.0}
DURATION_COST = {"weeks": 1.0, "months": 2 / 3, "years": 1 / 3, "decades": 0.0}


def _n_score(n: Optional[int]) -> Optional[float]:
    if n is None:
        return None
    return 1.0 if n < 50 else 2 / 3 if n < 200 else 1 / 3 if n < 1000 else 0.0


def readiness(card: HypothesisCard) -> Optional[float]:
    """1: approved drug (ChEMBL phase 4) or a non-compound intervention (programme, exercise, device); 0.5: a compound in
    clinical trials (phase 1-3); 0: a compound without a phase. None when the lookup fails."""
    labels = [i.label for i in card.pico.intervention]
    if not labels:
        return None
    try:
        from hyparena.card.entities import subject_compounds
        comps = [c for lab in labels for c in (subject_compounds(lab, card) or [])]
    except Exception:
        return None
    if not comps:
        return 1.0
    phase = max((c.max_phase or 0) for c in comps)
    return 1.0 if phase >= 4 else 0.5 if phase >= 1 else 0.0


def feasibility(card: HypothesisCard) -> Optional[float]:
    e = card.decisive_experiment
    parts = [SYSTEM_COST.get(e.system), DURATION_COST.get(e.duration_class), _n_score(e.n_planned), readiness(card)]
    known = [p for p in parts if p is not None]
    return round(sum(known) / len(known), 3) if known else None


def extras(card: HypothesisCard, ver_claims: list[ClaimVerification], v3: dict, as_of: str = "",
           variant: str = "v3") -> dict:
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
        "feasibility": feasibility(card),
        "weakest_level": min(levels, key=lw) if levels else "unverified",
        "human_outcome": any(r3.species_key(r.species) == "human" or r3.human_claim(c) and r3.context_level(r) == "exact"
                             for r, c in out_recs),
        "best_effect_outcome": max(effects, key=EFFECT_LADDER.index, default="none"),
        "unverified_links": sum(1 for x in levels if x == "unverified"),
        "momentum": round(sum(1 for y in years if t_year and y >= t_year - 4) / len(years), 3) if years and t_year else None,
    }

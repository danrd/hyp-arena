"""ASPID over the axes of method v3 (configs/profiles_v3.yaml; method-v3.md section 13).

The v3 rules give each hypothesis absolute axes (P, W, I and the headroom I); this module ranks them with ASPID
(hyparena/aspid.py: random weights under an order of importance, expected value, spread, pairwise winning probabilities)
instead of the single product V = P x W x I. P, I and I_headroom are on log scales, so the additive ASPID value is a randomly
weighted geometric mean (no compensation of a near-zero plausibility); W is ordinal (random monotone mapping of its three
levels). Hypotheses filtered by the gate are not ranked. Values sit on fixed scales, so a hypothesis's expected value does not
depend on the rest of the pool.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from hyparena.aspid import AggregationResult, IndicatorSpec, Profile, aggregate

PROFILES = Path(__file__).resolve().parents[2] / "configs" / "profiles_v3.yaml"
P_FLOOR = 0.01                    # P below this (a long unsupported chain) sits at the bottom of the scale
SPECS = {
    "P": IndicatorSpec("P", "cardinal", bounds=(P_FLOOR, 1.0), log=True, note="plausibility, product over the chain"),
    "W": IndicatorSpec("W", "ordinal", levels=("local", "organ", "hallmark"), note="scope from supported links"),
    "I": IndicatorSpec("I", "cardinal", bounds=(0.0, 1.0), note="informativeness of the stated experiment (v3.4: 0-1, linear)"),
    "I_headroom": IndicatorSpec("I_headroom", "cardinal", bounds=(0.0, 1.0),
                                note="informativeness if the experiment cut off every supported alternative"),
    "feasibility": IndicatorSpec("feasibility", "cardinal", bounds=(0.0, 1.0),
                                 note="section 9.4: system, duration, planned n, readiness of the intervention (v3_extra)"),
    "best_design_outcome": IndicatorSpec("best_design_outcome", "ordinal",
                                         levels=("none", "cells", "animal", "observational", "review", "non_randomised",
                                                 "meta_analysis", "rct"), note="best design for the outcome link"),
    "independent_outcome": IndicatorSpec("independent_outcome", "cardinal", bounds=(0.0, 5.0),
                                         note="independent sources for the outcome link, saturating at 5"),
    "against_share": IndicatorSpec("against_share", "cardinal", bounds=(0.0, 1.0), higher_is_better=False,
                                   note="share of the chain's weight against"),
    "endpoint_clinical": IndicatorSpec("endpoint_clinical", "ordinal",
                                       levels=("biomarker", "patient_reported", "function", "clinical_event"),
                                       note="how close the trial's primary endpoint is to a clinical outcome (estimand check, "
                                            "specs/estimand-2026-11-06.yaml); unknown when the two families disagree"),
    "trend_pubmed": IndicatorSpec("trend_pubmed", "cardinal", bounds=(-0.5, 1.5),
                                  note="rising attention: log ratio of PubMed records on the intervention, last 3 years vs the "
                                       "3 before, net of PubMed growth (specs/trend-genetics-2026-11-06.yaml); clipped to the bounds"),
    "chain_state": IndicatorSpec("chain_state", "cardinal", bounds=(-1.0, 1.0),
                                 note="v3.5: mean over the chain's slots of 2S - 1 (-1 refuted, 0 unknown, +1 supported)"),
    "support_share": IndicatorSpec("support_share", "cardinal", bounds=(0.0, 1.0),
                                   note="mean support of the chain's slots, max(0, 2 (S - 0.5)) (v3.3, specs/v33-2026-11-06.yaml)"),
    "N": IndicatorSpec("N", "ordinal", levels=("new_context", "translation", "analog", "new_combination", "new_link"),
                       note="novelty: distance to what was asked before the date (v3.4, specs/v34-frontier-2026-11-07.yaml)"),
    "leverage": IndicatorSpec("leverage", "cardinal", bounds=(0.0, 2 / 3),
                              note="support share gained if the bottleneck reached S 5/6, times the support of the rest (v3.4)"),
    "W_potential": IndicatorSpec("W_potential", "ordinal", levels=("local", "organ", "hallmark"),
                                 note="scope with the bottleneck confirmed (v3.4)"),
    "literature_density": IndicatorSpec("literature_density", "cardinal", bounds=(0.0, 6.0), higher_is_better=False,
                                        note="log10(1 + PubMed records on the intervention and the outcome before the date) (v3.4)"),
    "ai_role": IndicatorSpec("ai_role", "ordinal", levels=("none", "analysis", "in_the_loop", "intervention"),
                             note="role of AI in the hypothesis (normalize_card/v10, verbatim span or none)"),
}


def load(path: Path = PROFILES) -> dict[str, tuple[Profile, list[str]]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))["profiles"]
    return {name: (Profile(name=name, version=str(p.get("version", "1")), tiers=p["tiers"], description=p.get("description", "")),
                   list(p["indicators"])) for name, p in data.items()}


def values_of(v3: dict, extra: Optional[dict] = None) -> dict:
    """The indicator values of one hypothesis from its v3 result (V3Result.as_dict) and its additional indicators
    (v3_extra.extras); a missing additional value is unknown and drawn over its range."""
    e = extra or {}
    return {"P": max(P_FLOOR, v3["P"]), "W": v3["scope"], "I": v3["I"], "I_headroom": v3["headroom_I"],
            **{k: e.get(k) for k in ("feasibility", "best_design_outcome", "independent_outcome", "against_share",
                                    "endpoint_clinical", "ai_role", "support_share", "chain_state", "N", "leverage",
                                    "W_potential", "literature_density")},
            "trend_pubmed": None if e.get("trend_pubmed") is None else min(1.5, max(-0.5, e["trend_pubmed"]))}


def rank(results: dict[str, tuple[dict, Optional[dict]]], profile: str, K: int = 10000, seed: int = 0) -> Optional[AggregationResult]:
    """`results` {unit: (v3 result dict, additional indicators or None)}; units filtered by the gate are left out."""
    prof, ids = load()[profile]
    vals = {u: {k: values_of(v3, v2)[k] for k in ids} for u, (v3, v2) in results.items() if v3.get("gate") == "pass"}
    if not vals:
        return None
    return aggregate(vals, [SPECS[k] for k in ids], prof, K=K, seed=seed)

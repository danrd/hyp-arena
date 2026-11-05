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
    "I": IndicatorSpec("I", "cardinal", bounds=(1 / 3, 1.0), log=True, note="informativeness of the stated experiment"),
    "I_headroom": IndicatorSpec("I_headroom", "cardinal", bounds=(1 / 3, 1.0), log=True,
                                note="informativeness if the experiment cut off every supported alternative"),
    "feasibility": IndicatorSpec("feasibility", "ordinal", levels=("1", "0"),
                                 note="v2 path_to_human: 0 = human safety data exist (cheaper to test now)"),
}


def load(path: Path = PROFILES) -> dict[str, tuple[Profile, list[str]]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))["profiles"]
    return {name: (Profile(name=name, version=str(p.get("version", "1")), tiers=p["tiers"], description=p.get("description", "")),
                   list(p["indicators"])) for name, p in data.items()}


def values_of(v3: dict, v2_indicators: Optional[dict] = None) -> dict:
    """The indicator values of one hypothesis from its v3 result (V3Result.as_dict) and its v2 indicators."""
    feas = (v2_indicators or {}).get("path_to_human")
    return {"P": max(P_FLOOR, v3["P"]), "W": v3["scope"], "I": v3["I"], "I_headroom": v3["headroom_I"],
            "feasibility": str(feas) if feas is not None else None}


def rank(results: dict[str, tuple[dict, Optional[dict]]], profile: str, K: int = 10000, seed: int = 0) -> Optional[AggregationResult]:
    """`results` {unit: (v3 result dict, v2 indicators or None)}; units filtered by the gate are left out."""
    prof, ids = load()[profile]
    vals = {u: {k: values_of(v3, v2)[k] for k in ids} for u, (v3, v2) in results.items() if v3.get("gate") == "pass"}
    if not vals:
        return None
    return aggregate(vals, [SPECS[k] for k in ids], prof, K=K, seed=seed)

"""Ranking of verified cards (our method): admission → gate → known-result check → rule-based indicators →
aggregation under each preference profile → candidates robust across profiles. No LLM here: everything
below is computed from the declared and verified layers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from hyparena.aspid import AggregationResult, Profile, aggregate, load_profiles
from hyparena.card import indicators as ind
from hyparena.card.models import HypothesisCard, Verification
from hyparena.card.rules import admit, finalize


@dataclass
class Ranking:
    ranked: list[str]                                   # admitted, gate passed, not a known result
    values: dict[str, dict[str, object]]                # indicator values per ranked hypothesis
    by_profile: dict[str, AggregationResult]
    robust: list[str]                                   # P(top-k) >= threshold in every profile
    filtered: dict[str, str] = field(default_factory=dict)      # gate: hypothesis → reason
    known_results: list[str] = field(default_factory=list)
    not_admitted: dict[str, str] = field(default_factory=dict)  # hypothesis → decision and missing fields


def rank(items: list[tuple[HypothesisCard, Verification, Optional[dict]]], profiles: Optional[dict[str, Profile]] = None,
         K: int = 10000, seed: int = 0, k_top: int = 5, threshold: float = 0.5) -> Ranking:
    profiles = profiles or load_profiles()
    values, filtered, known, not_admitted = {}, {}, [], {}
    for card, ver, extra in items:
        adm = admit(card)
        if adm.decision != "accepted":
            not_admitted[card.id] = f"{adm.decision}: missing {', '.join(adm.missing_critical)}"
            continue
        ver = finalize(card, ver)
        if ver.evidence_profile.gate == "filtered":
            filtered[card.id] = ver.evidence_profile.gate_reason
            continue
        if ver.known_result:
            known.append(card.id)
            continue
        values[card.id] = ind.compute(card, ver, extra)
    by_profile = {name: aggregate(values, ind.INDICATORS, p, K=K, seed=seed, k_top=min(k_top, max(1, len(values))))
                  for name, p in profiles.items()} if values else {}
    robust = [h for h in values if by_profile and all(r.p_topk[h] >= threshold for r in by_profile.values())]
    return Ranking(ranked=list(values), values=values, by_profile=by_profile, robust=robust,
                   filtered=filtered, known_results=known, not_admitted=not_admitted)

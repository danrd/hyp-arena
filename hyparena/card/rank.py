"""Ranking of verified cards (our method): admission → gate → known-result check → rule-based indicators →
aggregation under each preference profile → candidates robust across profiles. No LLM here: everything
below is computed from the declared and verified layers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from hyparena.aspid import AggregationResult, Prefer, Profile, aggregate, load_profiles
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
    autonomous: dict[str, AggregationResult] = field(default_factory=dict)   # without expert constraints, when any
    expert_skipped: list = field(default_factory=list)          # pairwise choices naming a hypothesis not ranked


def rank(items: list[tuple[HypothesisCard, Verification, Optional[dict]]], profiles: Optional[dict[str, Profile]] = None,
         K: int = 10000, seed: int = 0, k_top: int = 5, threshold: float = 0.5,
         prefer: Optional[dict[Optional[str], list[Prefer]]] = None) -> Ranking:
    """`prefer`: expert pairwise choices by profile (None: every profile); the ranking is then also computed
    without them (autonomous mode, Aggregation_Spec 6a)."""
    from hyparena.card.expert import with_preferences
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
    run = lambda profs: {name: aggregate(values, ind.INDICATORS, p, K=K, seed=seed, k_top=min(k_top, max(1, len(values))))
                         for name, p in profs.items()} if values else {}
    skipped, autonomous = [], {}
    if prefer:
        kept = {k: [c for c in v if c.a in values and c.b in values] for k, v in prefer.items()}
        skipped = [c for v in prefer.values() for c in v if c.a not in values or c.b not in values]
        if any(kept.values()):
            autonomous = run(profiles)
            profiles = with_preferences(profiles, kept)
    by_profile = run(profiles)
    robust = [h for h in values if by_profile and all(r.p_topk[h] >= threshold for r in by_profile.values())]
    return Ranking(ranked=list(values), values=values, by_profile=by_profile, robust=robust,
                   filtered=filtered, known_results=known, not_admitted=not_admitted,
                   autonomous=autonomous, expert_skipped=skipped)

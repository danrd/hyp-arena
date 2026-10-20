"""Rule-based indicators for the aggregation (card spec, section 8a), computed from the declared card and its
verified layer. Every value is a fact derived from the card or `None` (unknown); unknowns are drawn uniformly
by the aggregation, never replaced by a default.

Not computable yet (left unknown until their inputs exist): cost and time of the decisive experiment
(reference-class tables), informativeness (prediction table, spec 8c), late start (species median lifespan
table). Novelty uses the verified claims only, not yet the knowledge graph."""
from __future__ import annotations

from typing import Optional

from hyparena.aspid import IndicatorSpec
from hyparena.card.models import RUNGS, HypothesisCard, Verification
from hyparena.card.rules import _all_claims, admissible, claim_rung, claim_status, same_intervention

INDICATORS: list[IndicatorSpec] = [
    IndicatorSpec("effect_level", "ordinal", levels=RUNGS),
    IndicatorSpec("robustness", "ordinal", levels=("single", "replicated")),
    IndicatorSpec("multi_site_positive", "ordinal", levels=("no", "positive")),
    IndicatorSpec("mechanism", "ordinal", levels=("unverified", "partial", "supported")),
    IndicatorSpec("novelty", "ordinal", levels=("translation", "analog", "new_link"),
                  note="from verified claims; knowledge-graph lookup not yet implemented"),
    IndicatorSpec("cost", "cardinal", bounds=(1e3, 1e8), log=True, higher_is_better=False,
                  note="USD of the decisive experiment; draft bounds; reference-class table not built yet"),
    IndicatorSpec("time", "cardinal", bounds=(7, 3650), log=True, higher_is_better=False,
                  note="days of the decisive experiment; draft bounds; reference-class table not built yet"),
    IndicatorSpec("translational_distance", "ordinal", levels=("phase0", "phase1", "phase2", "phase3", "phase4"),
                  note="ChEMBL max phase for compounds; rules for diet, procedures and genes open"),
    IndicatorSpec("late_start", "cardinal", bounds=(0.0, 1.0),
                  note="age at start / species median lifespan, capped at 1"),
    IndicatorSpec("both_sexes", "ordinal", levels=("one", "both")),
    IndicatorSpec("effect_size", "cardinal", bounds=(0.0, 30.0),
                  note="% change of lifespan at the effect level; cap 30% is a draft (spec 12)"),
    IndicatorSpec("informativeness", "cardinal", bounds=(0.0, 4.0),
                  note="alternatives the decisive experiment separates (prediction table), saturating at 4"),
]
BY_ID = {s.id: s for s in INDICATORS}


def compute(card: HypothesisCard, ver: Verification, extra: Optional[dict] = None) -> dict[str, object]:
    """Indicator values for one admitted, gate-passing hypothesis. `extra` carries values computed by other
    components when available: max_phase, cost_usd, time_days, late_start, informativeness."""
    extra = extra or {}
    prof = ver.evidence_profile
    pairs = _all_claims(card, ver)
    status = {cv.id: claim_status(cv, c) for c, cv in pairs}
    at_level = [r for c, cv in pairs
                if (c.role == "outcome" or (c.role in ("analog", "translation") and same_intervention(c, card)))
                and status[cv.id] == "supported" and claim_rung(c, cv) == prof.effect_level
                for r in cv.evidence if admissible(r, c)]
    sexes = {s for r in at_level for s in r.sexes}
    sizes = [r.effect_percent for r in at_level if r.effect_percent is not None]
    phase = extra.get("max_phase")
    return {
        "effect_level": prof.effect_level,
        "robustness": prof.robustness,
        "multi_site_positive": "positive" if prof.multi_site_program.get("outcome") == "positive" else "no",
        "mechanism": prof.mechanism if prof.mechanism != "refuted" else "unverified",
        "novelty": novelty(card, ver),
        "cost": extra.get("cost_usd"),
        "time": extra.get("time_days"),
        "translational_distance": f"phase{int(phase)}" if phase is not None else None,
        "late_start": extra.get("late_start"),
        "both_sexes": ("both" if len(sexes) >= 2 else "one") if sexes else None,
        "effect_size": max(sizes) if sizes else None,
        "informativeness": extra.get("informativeness"),
    }


def novelty(card: HypothesisCard, ver: Verification) -> str:
    """translation of a known finding to a new species · analog of a known intervention · new link
    (a known result is ranked separately and never reaches this point)."""
    pairs = _all_claims(card, ver)
    for c, cv in pairs:
        if c.role in ("analog", "translation") and same_intervention(c, card) and claim_status(cv, c) == "supported":
            return "translation"
    for c, cv in pairs:
        if c.role == "analog" and claim_status(cv, c) == "supported":
            return "analog"
        if any(r.qualifiers_match.get("intervention_match") in ("related_compound", "class")
               and r.quote_role == "finding" for r in cv.evidence):
            return "analog"
    return "new_link"

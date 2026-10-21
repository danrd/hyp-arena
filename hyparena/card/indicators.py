"""Rule-based indicators for the aggregation (card spec, section 8a), computed from the declared card and its
verified layer. Every value is a fact derived from the card or `None` (unknown); unknowns are drawn uniformly
by the aggregation, never replaced by a default.

Not computable yet (left unknown until their inputs exist): informativeness (prediction table, spec 8c, stage
C); late start needs the median and verbal-age tables (configs/lifespan_medians.yaml, values not filled yet). Novelty uses the verified claims only, not yet the knowledge
graph. Cost, time and translational distance were replaced by the ordinal `path_to_human` (2026-10-20);
`next_step` is shown outside the ranking."""
from __future__ import annotations

from typing import Optional

from hyparena.aspid import IndicatorSpec
from hyparena.card.models import RUNGS, HypothesisCard, Verification
from hyparena.card.rules import STRAIN_ANALOG, _all_claims, admissible, claim_rung, claim_status, same_intervention

INDICATORS: list[IndicatorSpec] = [
    IndicatorSpec("effect_level", "ordinal", levels=RUNGS),
    IndicatorSpec("robustness", "ordinal", levels=("single", "replicated")),
    IndicatorSpec("multi_site_positive", "ordinal", levels=("no", "positive")),
    IndicatorSpec("mechanism", "ordinal", levels=("unverified", "partial", "supported")),
    IndicatorSpec("novelty", "ordinal", levels=("new_context", "translation", "analog", "new_link"),
                  note="from verified claims; knowledge-graph lookup not yet implemented"),
    IndicatorSpec("path_to_human", "ordinal", levels=("2", "1", "0"),
                  note="preliminary steps before a human trial: safety package without human safety data, "
                       "mouse study without a supported mammalian effect; fewer is better"),
    IndicatorSpec("late_start", "cardinal", bounds=(0.0, 1.0),
                  note="age at start / species median lifespan, capped at 1; a verbal age gives an interval"),
    IndicatorSpec("both_sexes", "ordinal", levels=("one", "both")),
    IndicatorSpec("effect_size", "cardinal", bounds=(0.0, 30.0),
                  note="% change of lifespan at the effect level; cap 30% is a draft (spec 12)"),
    IndicatorSpec("informativeness", "cardinal", bounds=(0.0, 4.0),
                  note="alternatives the decisive experiment separates (prediction table), saturating at 4"),
]
BY_ID = {s.id: s for s in INDICATORS}


def compute(card: HypothesisCard, ver: Verification, extra: Optional[dict] = None) -> dict[str, object]:
    """Indicator values for one admitted, gate-passing hypothesis. `extra` carries values computed by other
    components when available: human_safety, late_start, informativeness."""
    extra = extra or {}
    prof = ver.evidence_profile
    pairs = _all_claims(card, ver)
    status = {cv.id: claim_status(cv, c) for c, cv in pairs}
    at_level = [r for c, cv in pairs
                if (c.role == "outcome" or (c.role in ("analog", "translation") and same_intervention(c, card)))
                and status[cv.id] == "supported" and claim_rung(c, cv) == prof.effect_level
                for r in cv.evidence if admissible(r, c)]
    sexes = {r.sex for r in at_level if r.sex != "unknown"}
    sizes = [r.effect_percent for r in at_level if r.effect_percent is not None]
    return {
        "effect_level": prof.effect_level,
        "robustness": prof.robustness,
        "multi_site_positive": "positive" if prof.multi_site_program.get("outcome") == "positive" else "no",
        "mechanism": prof.mechanism if prof.mechanism != "refuted" else "unverified",
        "novelty": novelty(card, ver),
        "path_to_human": path_to_human(prof.effect_level, extra.get("human_safety")),
        "late_start": tuple(extra["late_start"]) if isinstance(extra.get("late_start"), list) else extra.get("late_start"),
        "both_sexes": ("both" if "both" in sexes or {"male", "female"} <= sexes else "one") if sexes else None,
        "effect_size": max(sizes) if sizes else None,
        "informativeness": extra.get("informativeness"),
    }


MAMMALIAN = ("mammals", "human_markers", "human_clinical")


def path_to_human(effect_level: str, human_safety: Optional[bool]) -> Optional[str]:
    """Number of preliminary steps before a human trial (spec 8a): a preclinical safety package when there
    are no human safety data, a mouse study when there is no supported mammalian effect. Unknown when the
    safety data cannot be decided (a gene target without a drug, an unresolved compound)."""
    if human_safety is None:
        return None
    return str(int(not human_safety) + int(effect_level not in MAMMALIAN))


def novelty(card: HypothesisCard, ver: Verification) -> str:
    """new context (the same intervention and species already work in another strain, sex, dose or start age)
    · translation of a known finding to a new species · analog of a known intervention · new link (a known
    result is ranked separately and never reaches this point)."""
    pairs = _all_claims(card, ver)
    for c, cv in pairs:
        if c.note.startswith(STRAIN_ANALOG) and claim_status(cv, c) == "supported":
            return "new_context"
    out = card.outcome_claim
    cv_out = next((cv for c, cv in pairs if out and c.id == out.id), None)
    if cv_out is not None and claim_status(cv_out, out) == "supported":
        return "new_context"                              # supported, but not in exactly this context (else known)
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

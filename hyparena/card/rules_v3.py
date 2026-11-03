"""Method v3 rules (docs/spec/method-v3.md, sections 3-6 and 9): record weight on ordinal scales, link strength, the gate,
plausibility P, scope W, informativeness I, promise V = P x W x I, evolution flags and the experiment headroom.

Pure functions over a card and its verification; no model calls. The v2 rules (hyparena/card/rules.py) are untouched; a run
with `method: v3` stores the result of `evaluate` next to the v2 output.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from hyparena.card import v3_levels as lv
from hyparena.card.models import Claim, ClaimVerification, EvidenceRecord, HypothesisCard, ProposedAlternative
from hyparena.card.rules import species_key

ADJACENT_KEYS = {"population", "age_at_start", "dose", "comparator", "species", "sex"}
TOP_DESIGNS = ("rct", "meta_analysis")
# link-strength thresholds on the summed weights (one RCT with >= 300 participants, a large between-group effect and an exact
# context weighs 1.0); levels, not tuned numbers: strong ~ two such trials, moderate ~ one trial of 100-299, weak ~ anything
STRONG, MODERATE = 1.5, 0.6
I_CAP = 1.5                                        # "one and a half well-supported alternatives cut off" is the maximum


def human_claim(claim: Claim) -> bool:
    return species_key(claim.qualifiers.get("species", "")) == "human" or species_key(claim.object.label) == "human"


def context_level(rec: EvidenceRecord) -> Optional[str]:
    """exact / adjacent / class, or None when the record is about another intervention altogether."""
    im = rec.qualifiers_match.get("intervention_match", "exact")
    no = {k for k, v in rec.qualifiers_match.items() if v == "no" and k != "intervention_match"}
    if no - ADJACENT_KEYS:
        return None
    if im in ("class", "related_compound"):
        return "class"
    return "adjacent" if no else "exact"


def usable(rec: EvidenceRecord) -> bool:
    """A finding, or a review sentence restating one trial's result (section 9.1); not speculation, not retracted."""
    if "retracted" in rec.flags or rec.quote_role == "speculation":
        return False
    return rec.quote_role == "finding" or bool(rec.reports_trial)


def record_design(rec: EvidenceRecord) -> str:
    if rec.reports_trial and not rec.primary_record:
        return "rct"                                   # a restated trial weighs as an RCT of unknown size until its paper is found
    if rec.design != "unknown":
        return rec.design
    st = (rec.study_type or "").lower()
    return {"rct": "rct", "open_label_pilot": "non_randomised", "observational": "observational", "review": "review",
            "primary_experiment": "animal" if species_key(rec.species) != "human" else "other"}.get(st, "other")


def record_weight(rec: EvidenceRecord, claim: Claim, against: bool) -> float:
    """design x precision x effect x comparison x context, each a level of its scale (i/k)."""
    if not usable(rec):
        return 0.0
    ctx = context_level(rec)
    if ctx is None:
        return 0.0
    w = lv.design_weight(record_design(rec), human_claim(claim))
    w *= lv.weight("precision", lv.precision_band(rec.n_total))
    effect = "large" if against else rec.effect_class           # a clear null weighs like a clear positive (section 3)
    w *= lv.weight("effect", effect)
    w *= lv.weight("comparison", rec.comparison if rec.comparison != "unknown" else "none")
    w *= lv.weight("context", ctx)
    return w


def _independent(records: list[EvidenceRecord]) -> int:
    return len({r.reports_trial or r.lab_or_cohort or r.record_id for r in records})


def strong_refutation(cv: ClaimVerification, claim: Claim) -> bool:
    """The gate (section 3): a top-design, between-group record against in the claim's population (exact context), and no
    record for of that level."""
    def top(r):
        return usable(r) and record_design(r) in TOP_DESIGNS and r.comparison in ("between_groups", "unknown") \
            and context_level(r) == "exact"
    against = [r for r in cv.counterevidence if top(r) and (r.comparison == "between_groups" or r.reports_trial)]
    support = [r for r in cv.evidence if top(r) and r.comparison == "between_groups"]
    return bool(against) and not support


def link_level(cv: Optional[ClaimVerification], claim: Claim) -> tuple[str, float, float]:
    """(level, weight for, weight against). No verification or no usable record: unverified."""
    if cv is None:
        return "unverified", 0.0, 0.0
    if strong_refutation(cv, claim):
        return "refuted", 0.0, sum(record_weight(r, claim, True) for r in cv.counterevidence)
    f_recs = [r for r in cv.evidence if record_weight(r, claim, False) > 0]
    a_recs = [r for r in cv.counterevidence if record_weight(r, claim, True) > 0]
    F = sum(record_weight(r, claim, False) for r in f_recs)
    A = sum(record_weight(r, claim, True) for r in a_recs)
    if F == 0 and A == 0:
        return "unverified", F, A
    if A > 0 and A >= F / 2:
        return "contested", F, A
    if F >= STRONG and _independent(f_recs) >= 2:
        return "strong", F, A
    if F >= MODERATE:
        return "moderate", F, A
    return "weak", F, A


def established_by_approval(claim: Claim, card: HypothesisCard) -> bool:
    """Section 9.2 (simplified, 2026-11-03): an engagement link whose subject is an approved drug (ChEMBL max phase 4) with a
    known mechanism of action. The spec asks that the target match the link; ChEMBL gives target ids, not names, so the match is
    not checked yet and the level is "moderate" (5/6), not 0.9."""
    if claim.link != "engagement":
        return False
    try:
        from hyparena.card.entities import subject_compounds
        comps = subject_compounds(claim.subject.label, card) or []
    except Exception:
        return False
    return len(comps) == 1 and comps[0].max_phase == 4 and bool(comps[0].targets)


def chain(card: HypothesisCard) -> list[Claim]:
    """The claims of the mechanism chain: those with a `link`; a v2 card without links: outcome, mechanism and premise claims."""
    linked = [c for c in card.claims if c.link]
    return linked or [c for c in card.claims if c.role in ("outcome", "mechanism", "premise")]


def _words(s: str) -> set[str]:
    import re
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2}


def outcome_group(card: HypothesisCard, links: list[Claim]) -> tuple[list[Claim], Optional[Claim]]:
    """Parallel outcomes (several claims at the outcome place of the chain: mass, strength, function) are one link, not a
    conjunction (user decision 2026-11-03). Returns (the parallel outcome claims, the one matching the primary outcome of the
    stated experiment, or None when no single one matches)."""
    outs = [c for c in links if c.link == "outcome" or (not c.link and c.role == "outcome")]
    if len(outs) <= 1:
        return outs, (outs[0] if outs else None)
    target = _words(card.decisive_experiment.primary_outcome) | _words(card.pico.outcome.metric)
    scored = sorted(((len(target & (_words(c.object.label) | _words(c.qualifiers.get("measure", "")))), c) for c in outs),
                    key=lambda t: -t[0])
    if target and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return outs, scored[0][1]
    return outs, None


@dataclass
class V3Result:
    gate: str = "pass"                                  # pass | filtered
    gate_reason: str = ""
    P: float = 0.0
    W: float = 0.0
    I: float = 0.0
    V: float = 0.0
    links: dict[str, str] = field(default_factory=dict)         # claim id -> level
    weights: dict[str, list[float]] = field(default_factory=dict)  # claim id -> [for, against]
    scope: str = "local"
    alternatives: dict[str, dict] = field(default_factory=dict)  # alternative id -> {a, d}
    weakest: str = ""
    headroom_I: float = 0.0
    headroom_V: float = 0.0
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate(card: HypothesisCard, ver_claims: list[ClaimVerification],
             alt_verifications: Optional[dict[str, ClaimVerification]] = None) -> V3Result:
    by_id = {cv.id: cv for cv in ver_claims}
    links = chain(card)
    res = V3Result()
    if not links:
        res.flags.append("build_mechanism")
        return res
    for c in links:
        level, F, A = link_level(by_id.get(c.id), c)
        if level in ("unverified", "weak") and established_by_approval(c, card):
            level = "moderate"
            res.flags.append(f"{c.id}_established_by_approval")
        res.links[c.id], res.weights[c.id] = level, [round(F, 3), round(A, 3)]
        if level == "refuted" and (c.role in ("outcome", "mechanism") or c.link in ("engagement", "pathway", "effect", "outcome")):
            res.gate, res.gate_reason = "filtered", f"{c.id} refuted by a randomised between-group finding against"
    # plausibility: product over the chain; parallel outcomes count once: the primary outcome, else their mean
    outs, primary = outcome_group(card, links)
    P = 1.0
    for c in links:
        if c in outs:
            continue
        P *= lv.weight("link", res.links[c.id])
    if outs:
        P *= lv.weight("link", res.links[primary.id]) if primary is not None else \
            sum(lv.weight("link", res.links[c.id]) for c in outs) / len(outs)
    res.P = round(P, 4)
    res.weakest = min(links, key=lambda c: lv.weight("link", res.links[c.id])).id
    # scope: only links at least weak
    supported = [c for c in links if res.links[c.id] in ("weak", "moderate", "strong")]
    if any(c.object.hallmark or c.subject.hallmark for c in supported):
        res.scope = "hallmark"
    elif any(c.link in ("engagement", "pathway", "effect") or c.role == "mechanism" for c in supported):
        res.scope = "organ"
    res.W = round(lv.weight("scope", res.scope), 4)
    # informativeness over the proposed alternatives
    alt_verifications = alt_verifications or {}
    total = best = 0.0
    for alt in card.proposed_alternatives:
        a_claim = Claim(id=alt.id, subject=alt.subject, relation=alt.relation, object=alt.object, qualifiers=alt.qualifiers,
                        role="premise", source_span="")
        level, F, A = link_level(alt_verifications.get(alt.id), a_claim)
        a = lv.weight("link", level) if level in ("weak", "moderate", "strong") else 0.0   # no support: weighs nothing
        d = max(lv.weight("discrimination", alt.on_positive), lv.weight("discrimination", alt.on_negative))
        res.alternatives[alt.id] = {"a": round(a, 3), "d": d, "level": level}
        total += a * d
        best += a
    # no supported alternative: the lowest step 1/3 (user decision 2026-11-03: undeveloped is not empty); with supported ones
    # I = 1/3 + 2/3 x their informativeness, so a hypothesis with alternatives never ranks below one without
    supported_alts = [v for v in res.alternatives.values() if v["a"] > 0]
    raw, raw_best = min(1.0, total / I_CAP), min(1.0, best / I_CAP)
    res.I = round(1 / 3 + 2 / 3 * raw, 4) if supported_alts else round(1 / 3, 4)
    res.headroom_I = round(1 / 3 + 2 / 3 * raw_best, 4) if supported_alts else round(1 / 3, 4)
    res.V = round(res.P * res.W * res.I, 5) if res.gate == "pass" else 0.0
    res.headroom_V = round(res.P * res.W * res.headroom_I, 5) if res.gate == "pass" else 0.0
    # evolution flags (section 5): never filters
    if not any(c.link in ("engagement", "pathway", "effect") or c.role == "mechanism" for c in links):
        res.flags.append("build_mechanism")
    if not card.proposed_alternatives or all(v["a"] == 0 for v in res.alternatives.values()):
        res.flags.append("name_supported_alternatives")
    elif raw_best - raw >= 0.2:                            # on the raw scale: the stated experiment leaves supported alternatives uncut
        res.flags.append("improve_experiment")
    if any(r.reports_trial and not r.primary_record for cv in ver_claims for r in cv.evidence + cv.counterevidence):
        res.flags.append("find_primary_report")
    if any(res.links[c.id] == "contested" for c in links):
        res.flags.append("contested_link")
    return res

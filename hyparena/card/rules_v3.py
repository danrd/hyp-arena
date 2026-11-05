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
VARIANTS = ("v3", "v3.1")                          # v3.1: method-v3.md section 12 (2026-11-05); "v3" is what runs record
PRECLINICAL_LINKS = ("delivery", "engagement", "pathway", "effect")


def _lw(level: str, variant: str) -> float:
    return lv.weight("link_v31" if variant == "v3.1" else "link", level)


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


def usable(rec: EvidenceRecord, variant: str = "v3") -> bool:
    """A finding, or a review sentence restating one trial's result (section 9.1); not speculation, not retracted (v3.1: also
    when PubMed itself marks the paper retracted, section 12 point 7)."""
    if "retracted" in rec.flags or rec.quote_role == "speculation":
        return False
    if variant == "v3.1" and "retracted_pubmed" in rec.flags:
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


def record_weight(rec: EvidenceRecord, claim: Claim, against: bool, variant: str = "v3") -> float:
    """design x precision x effect x comparison x context, each a level of its scale (i/k). v3.1 (section 12 point 1): the
    links before the outcome (delivery, engagement, pathway, effect) take the design scale of preclinical claims (cells,
    review, primary study), so the distance to the clinic is charged once, on the outcome link; the context factor still
    charges another species or population on every record."""
    if not usable(rec, variant):
        return 0.0
    ctx = context_level(rec)
    if ctx is None:
        return 0.0
    preclinical = variant == "v3.1" and claim.link in PRECLINICAL_LINKS
    w = lv.design_weight(record_design(rec), human_claim(claim) and not preclinical)
    w *= lv.weight("precision", lv.precision_band(rec.n_total))
    effect = "large" if against else rec.effect_class           # a clear null weighs like a clear positive (section 3)
    w *= lv.weight("effect", effect)
    w *= lv.weight("comparison", rec.comparison if rec.comparison != "unknown" else "none")
    w *= lv.weight("context", ctx)
    return w


def _independent(records: list[EvidenceRecord]) -> int:
    return len({r.reports_trial or r.lab_or_cohort or r.record_id for r in records})


def strong_refutation(cv: ClaimVerification, claim: Claim, variant: str = "v3") -> bool:
    """The gate (section 3): a top-design, between-group record against in the claim's population (exact context), and no
    record for of that level."""
    def top(r):
        return usable(r, variant) and record_design(r) in TOP_DESIGNS and r.comparison in ("between_groups", "unknown") \
            and context_level(r) == "exact"
    against = [r for r in cv.counterevidence if top(r) and (r.comparison == "between_groups" or r.reports_trial)]
    support = [r for r in cv.evidence if top(r) and r.comparison == "between_groups"]
    return bool(against) and not support


def link_level(cv: Optional[ClaimVerification], claim: Claim, variant: str = "v3") -> tuple[str, float, float]:
    """(level, weight for, weight against). No verification or no usable record: unverified."""
    if cv is None:
        return "unverified", 0.0, 0.0
    if strong_refutation(cv, claim, variant):
        return "refuted", 0.0, sum(record_weight(r, claim, True, variant) for r in cv.counterevidence)
    f_recs = [r for r in cv.evidence if record_weight(r, claim, False, variant) > 0]
    a_recs = [r for r in cv.counterevidence if record_weight(r, claim, True, variant) > 0]
    F = sum(record_weight(r, claim, False, variant) for r in f_recs)
    A = sum(record_weight(r, claim, True, variant) for r in a_recs)
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


def approval_matches_target(claim: Claim, card: HypothesisCard) -> bool:
    """v3.1 (section 12 point 5): the approval rule only when the engagement link names one approved drug (phase 4) and one
    of its ChEMBL mechanism targets is the link's object (a target name, a component description or a gene symbol appears
    in the object label as words). Unresolved names or network trouble: no bonus, the link goes through the literature."""
    import re
    if not established_by_approval(claim, card):
        return False
    try:
        from hyparena.card.entities import subject_compounds
        from hyparena.tools.compounds import target_names
        comp = (subject_compounds(claim.subject.label, card) or [None])[0]
        names = {n for t in comp.targets for n in target_names(t)}
    except Exception:
        return False
    obj = " " + re.sub(r"[^a-z0-9]+", " ", claim.object.label.lower()) + " "
    return any(len(n) >= 3 and " " + re.sub(r"[^a-z0-9]+", " ", n).strip() + " " in obj for n in names)


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
             alt_verifications: Optional[dict[str, ClaimVerification]] = None, variant: str = "v3") -> V3Result:
    """`variant` "v3" (what runs record) or "v3.1" (method-v3.md section 12; applied offline to saved records)."""
    if variant not in VARIANTS:
        raise ValueError(f"variant {variant!r} not in {VARIANTS}")
    by_id = {cv.id: cv for cv in ver_claims}
    links = chain(card)
    res = V3Result()
    if not links:
        res.flags.append("build_mechanism")
        return res
    for c in links:
        level, F, A = link_level(by_id.get(c.id), c, variant)
        approved = approval_matches_target(c, card) if variant == "v3.1" else established_by_approval(c, card)
        if level in ("unverified", "weak") and approved:
            level = "moderate"
            res.flags.append(f"{c.id}_established_by_approval")
        res.links[c.id], res.weights[c.id] = level, [round(F, 3), round(A, 3)]
        if level == "refuted" and (c.role in ("outcome", "mechanism") or c.link in ("engagement", "pathway", "effect", "outcome")):
            res.gate, res.gate_reason = "filtered", f"{c.id} refuted by a randomised between-group finding against"
    # plausibility: product over the chain; parallel outcomes count once: the primary outcome, else their mean
    # v3.1 (section 12 point 4): consecutive pathway links (a cascade written as several steps) are one slot, their
    # geometric mean, so that describing a pathway in more detail does not by itself lower P
    outs, primary = outcome_group(card, links)
    P = 1.0
    run: list[float] = []
    for c in links + [None]:
        if c is not None and variant == "v3.1" and c.link == "pathway" and c not in outs:
            run.append(_lw(res.links[c.id], variant))
            continue
        if run:
            prod = 1.0
            for x in run:
                prod *= x
            P *= prod ** (1 / len(run))
            run = []
        if c is None or c in outs:
            continue
        P *= _lw(res.links[c.id], variant)
    if outs:
        P *= _lw(res.links[primary.id], variant) if primary is not None else \
            sum(_lw(res.links[c.id], variant) for c in outs) / len(outs)
    res.P = round(P, 4)
    res.weakest = min(links, key=lambda c: _lw(res.links[c.id], variant)).id
    # scope: only links at least weak; v3.1 (section 12 point 6a): a hallmark only on a link at least moderate, a hallmark
    # on a weak link counts as an organ or system
    supported = [c for c in links if res.links[c.id] in ("weak", "moderate", "strong")]
    hallmark_ok = [c for c in supported if variant != "v3.1" or res.links[c.id] in ("moderate", "strong")]
    if any(c.object.hallmark or c.subject.hallmark for c in hallmark_ok):
        res.scope = "hallmark"
    elif variant == "v3.1" and any(c.object.hallmark or c.subject.hallmark for c in supported):
        res.scope = "organ"
    elif any(c.link in ("engagement", "pathway", "effect") or c.role == "mechanism" for c in supported):
        res.scope = "organ"
    res.W = round(lv.weight("scope", res.scope), 4)
    # informativeness over the proposed alternatives
    alt_verifications = alt_verifications or {}
    total = best = 0.0
    for alt in card.proposed_alternatives:
        a_claim = Claim(id=alt.id, subject=alt.subject, relation=alt.relation, object=alt.object, qualifiers=alt.qualifiers,
                        role="premise", source_span="")
        level, F, A = link_level(alt_verifications.get(alt.id), a_claim, variant)
        if level not in ("weak", "moderate", "strong"):
            a = 0.0                                   # no support: weighs nothing
        elif variant == "v3.1":                       # section 12 point 6b: support above unverified, steps 1/3, 2/3, 1
            a = lv.weight("alt_support_v31", level)
        else:
            a = lv.weight("link", level)
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
    if variant == "v3.1" and any("retracted_pubmed" in r.flags for cv in ver_claims for r in cv.evidence + cv.counterevidence):
        res.flags.append("retracted_source_dropped")
    if any(res.links[c.id] == "contested" for c in links):
        res.flags.append("contested_link")
    return res

"""Method v3.2 (method-v3.md section 13, user decision 2026-11-06): continuous scores, so that hypotheses whose links are all
"weak" are still told apart. Applied offline to saved records; runs record v3.

On top of v3.1 (rules_v3 variant "v3.1": preclinical design scale before the outcome, retractions, approval with a matching
target, pathway cascades as one slot):
- precision continuous in n: min(1, log n / log 300), floor 1/4 (unknown n stays 1/4);
- effect continuous where the phrase gives a ratio or a standardised difference: d = |ln ratio| * sqrt(3) / pi (logit
  conversion) or |d|, weight 1/4 + 3/4 * min(1, d / 0.8); otherwise the rule-A class as before; a record against keeps the top
  effect weight (a clear null weighs like a clear positive);
- link strength S = (c F + 1) / (c (F + A) + 2): the mean of Beta(1 + cF, 1 + cA), with F and A the summed record weights. No
  record: 0.5; conflict: about 0.5 with a narrow interval. c is anchored so that F = 0.6 with nothing against gives 5/6, the v3
  "moderate" (c = 4 / 0.6); its sensitivity is checked at +-50%. The gate (strong refutation) stays the v3 rule;
- P = product of S over the slots (outcome group and pathway cascades as in v3.1), with a 90% interval from the Beta quantiles
  of each link;
- alternative support a = max(0, 2 (S - 0.5)): continuous above "no record";
- scope W is not a factor of V: V = P x I; W stays an indicator of ASPID;
- fold=True (2026-11-06, specs/v32-independence-fold-2026-11-06.yaml): records of one independence group (one trial in
  several papers) count as one source: the heaviest fully, the rest with FOLD_REST.

v3.3 = evaluate(..., fold=True, neutral_unverified=True) (specs/v33-2026-11-06.yaml): a link with no usable record on either
side counts as 1 in P and its interval instead of 0.5, and `coverage` (share of the chain's slots with a usable record or
established by approval) is reported; the ASPID indicator is `support_share`, the mean over the slots of
max(0, 2 (S - 0.5)): how much of the chain is supported, continuous (amendment before scoring, specs/v33-2026-11-06.yaml).

v3.4 = evaluate(..., v34=True) (specs/v34-frontier-2026-11-07.yaml), fold on: P is non-refutation, the product over the
slots of R = (1 + cF) / (1 + cF + cA) (1 when nothing is against; support is in support_share alone; no interval); on the
outcome link of a claim about humans another species is charged by the design scale only; on the links before the outcome
precision is a constant 1/2.
"""
from __future__ import annotations

import os

import math
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Optional

from hyparena.card import rules_v3 as r3
from hyparena.card import v3_levels as lv
from hyparena.card.effect_class import _FOLD, _RATIO, _SMD
from hyparena.card.models import Claim, ClaimVerification, EvidenceRecord, HypothesisCard

C_ANCHOR = 4 / 0.6
VARIANT_BASE = "v3.1"
FOLD_REST = 0.25        # fold=True: further records of one independence group (specs/v32-independence-fold-2026-11-06.yaml)


def group_key(rec: EvidenceRecord) -> str:
    return rec.reports_trial or rec.lab_or_cohort or rec.record_id


def side_weight(recs: list[EvidenceRecord], claim: Claim, against: bool, fold: bool, v34: bool = False) -> float:
    if not fold:
        return sum(record_weight(r, claim, against, v34) for r in recs)
    groups: dict[str, list[float]] = {}
    for r in recs:
        groups.setdefault(group_key(r), []).append(record_weight(r, claim, against, v34))
    total = 0.0
    for ws in groups.values():
        ws.sort(reverse=True)
        total += ws[0] + FOLD_REST * sum(ws[1:])
    return total


def precision(n: Optional[int]) -> float:
    if not n or n < 2:
        return 0.25
    return max(0.25, min(1.0, math.log(n) / math.log(300)))


def effect_weight(rec: EvidenceRecord, against: bool) -> float:
    if against:
        return 1.0
    p = (rec.effect_reported or "").replace("−", "-")
    d = None
    for rx, kind in ((_RATIO, "ratio"), (_FOLD, "ratio"), (_SMD, "d")):
        m = rx.search(p)
        if m:
            x = float(next(g for g in m.groups() if g).replace(" ", ""))
            if kind == "ratio" and x > 0:
                d = abs(math.log(x)) * math.sqrt(3) / math.pi
            elif kind == "d":
                d = abs(x)
            break
    if d is None:                                         # 2026-11-08: a raw difference with its 95% CI and n
        from hyparena.card.effect_class import d_from_ci
        d = d_from_ci(p, rec.n_total, rec.comparison)
    if d is None:
        if rec.effect_class == "unclear":                 # 2026-11-08: a percent change the extractor class missed
            from hyparena.card.effect_class import from_phrase
            c = from_phrase(p)
            if c != "unclear":
                return lv.weight("effect", c)
        return lv.weight("effect", rec.effect_class)
    return 0.25 + 0.75 * min(1.0, d / 0.8)


PRECLINICAL_PRECISION = 0.5    # v3.4: replicates of cells or animals are not comparable with trial participants


def _claim_fixes(claim: Claim, key: str) -> bool:
    """Does the claim itself fix this qualifier? (population: population, disease or age; species: a species or a human claim)"""
    q = claim.qualifiers or {}
    if key == "population":
        return any(q.get(x) for x in ("population", "disease", "age_at_start"))
    if key == "species":
        return bool(q.get("species")) or r3.human_claim(claim)
    return bool(q.get(key))


def only_claim_qualifiers(rec: EvidenceRecord, claim: Claim) -> EvidenceRecord:
    """v3.5 amendment (user decision 2026-11-08, specs/record-weight-2026-11-08.yaml context_variants.claim_qualifiers): a
    "no" in qualifiers_match counts only on a qualifier the claim fixes; the verifier marked sex, dose or population "no"
    for claims that say nothing about them (53 of 98 adjacent records)."""
    qm = {k: v for k, v in rec.qualifiers_match.items() if k == "intervention_match" or v != "no" or _claim_fixes(claim, k)}
    return rec if qm == rec.qualifiers_match else rec.model_copy(update={"qualifiers_match": qm})


def context_v34(rec: EvidenceRecord, claim: Claim) -> Optional[str]:
    """v3.4: on the outcome link of a claim about humans, another species is charged by the design scale only. Since
    2026-11-08 only the qualifiers the claim fixes count (only_claim_qualifiers); context_v34_verifier is the earlier rule."""
    return context_v34_verifier(only_claim_qualifiers(rec, claim), claim)


def context_v34_verifier(rec: EvidenceRecord, claim: Claim) -> Optional[str]:
    """The v3.4 context with every "no" of the verifier counted (before 2026-11-08)."""
    ctx = r3.context_level(rec)
    if ctx != "adjacent" or claim.link in r3.PRECLINICAL_LINKS or not r3.human_claim(claim):
        return ctx
    no = {k for k, v in rec.qualifiers_match.items() if v == "no" and k != "intervention_match"}
    return "exact" if no == {"species"} else ctx


NULL_POWER_D, NULL_POWER_N_UNKNOWN = 0.4, 40     # specs/link-scoring-2026-11-08.yaml, B


def null_power(n: Optional[int], comparison: str) -> float:
    """Power of a study to detect d = 0.4 at two-sided 5% (B): the weight of its null result."""
    n = n if n and n > 1 else NULL_POWER_N_UNKNOWN
    z = NULL_POWER_D * math.sqrt(n / 4 if comparison == "between_groups" else n) - 1.96
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


NULL_POWER = False          # set by evaluate(..., null_power=True); module switch so side_weight need not carry it


V36 = False                 # set by evaluate(..., v36=True)
DESIGN_GRADE3 = {"rct": 1.0, "meta_analysis": 1.0, "non_randomised": 0.5, "observational": 0.5}   # else 1/4
EFFECT_FULL_FROM = 0.25 + 0.75 * 0.5 / 0.8      # the continuous effect weight of d = 0.5 (medium)
LOGLR_LAMBDA = 2 * math.atanh(2 / 3) / 0.6      # F = 0.6 alone gives s = 2/3, as c did for the Beta


def record_weight_v36(rec: EvidenceRecord, claim: Claim, against: bool) -> float:
    """v3.6 (specs/record-weight-2026-11-08.yaml, user decision 2026-11-08): GRADE-shaped weight.
    design: on the outcome link of a human claim RCT and meta-analysis 1, non-randomised and observational 1/2, else 1/4
    (before the outcome the preclinical scale as before); precision: a null by its power (v3.5), a record for min(1, ln n /
    ln 300) (1/2 before the outcome); effect: a record for with a stated effect of at least medium size 1, else (small, none,
    not stated) 1/2; comparison: between groups 1, else 1/2; context: adjacent 1/2, exact and class 1."""
    if not r3.usable(rec, VARIANT_BASE):
        return 0.0
    ctx = context_v34(rec, claim)
    if ctx is None:
        return 0.0
    pre = claim.link in r3.PRECLINICAL_LINKS
    design = r3.record_design(rec)
    w = DESIGN_GRADE3.get(design, 0.25) if (r3.human_claim(claim) and not pre) else lv.design_weight(design, False)
    if against:
        w *= null_power(rec.n_total, rec.comparison)
    else:
        w *= PRECLINICAL_PRECISION if pre else precision(rec.n_total)
        w *= 1.0 if effect_weight(rec, False) >= EFFECT_FULL_FROM - 1e-9 else 0.5
    w *= 1.0 if rec.comparison == "between_groups" else 0.5
    w *= 0.5 if ctx == "adjacent" else 1.0
    return w


@contextmanager
def method(v36: bool = True):
    """The current rules for code that weighs records outside evaluate (reports, improvements): v3.6 by default."""
    global NULL_POWER, V36
    saved = NULL_POWER, V36
    NULL_POWER, V36 = True, v36
    try:
        yield
    finally:
        NULL_POWER, V36 = saved


def current_weight(rec: EvidenceRecord, claim: Claim, against: bool) -> float:
    """The record weight under the current rules (for reports)."""
    with method():
        return record_weight(rec, claim, against, True)


def current_factors(rec: EvidenceRecord, claim: Claim, against: bool) -> Optional[dict]:
    with method():
        return weight_factors(rec, claim, against, True)


def current_support(recs_for: list, recs_against: list, claim: Claim) -> float:
    """a = max(0, 2 (S - 0.5)) of a link or an alternative under the current rules."""
    with method():
        F, A = side_weight(recs_for, claim, False, True, True), side_weight(recs_against, claim, True, True, True)
        return max(0.0, 2 * (link_point(F, A) - 0.5))


def link_point(F: float, A: float, c: float = C_ANCHOR) -> float:
    """The strength S of a link: v3.6 sigmoid(lambda (F - A)) (the log-likelihood sum), else the Beta mean."""
    return 1 / (1 + math.exp(-LOGLR_LAMBDA * (F - A))) if V36 else strength(F, A, c)[0]


def record_weight(rec: EvidenceRecord, claim: Claim, against: bool, v34: bool = False) -> float:
    if V36:
        return record_weight_v36(rec, claim, against)
    if not r3.usable(rec, VARIANT_BASE):
        return 0.0
    ctx = context_v34(rec, claim) if v34 else r3.context_level(rec)
    if ctx is None:
        return 0.0
    preclinical = claim.link in r3.PRECLINICAL_LINKS
    w = lv.design_weight(r3.record_design(rec), r3.human_claim(claim) and not preclinical)
    if against and NULL_POWER:                            # B: the null weighs by the study's power (replaces precision and effect)
        w *= null_power(rec.n_total, rec.comparison)
    else:
        w *= PRECLINICAL_PRECISION if (v34 and preclinical) else precision(rec.n_total)
        w *= effect_weight(rec, against)
    w *= lv.weight("comparison", rec.comparison if rec.comparison != "unknown" else "none")
    w *= lv.weight("context", ctx)
    return w


def weight_factors(rec: EvidenceRecord, claim: Claim, against: bool, v34: bool = True) -> Optional[dict]:
    """The factors of record_weight, for display: {design, precision, effect, comparison, context: [label, value]}; None when the
    record does not count."""
    if not r3.usable(rec, VARIANT_BASE):
        return None
    ctx = context_v34(rec, claim) if v34 else r3.context_level(rec)
    if ctx is None:
        return None
    pre = claim.link in r3.PRECLINICAL_LINKS
    comp = rec.comparison if rec.comparison != "unknown" else "none"
    if V36:
        design = r3.record_design(rec)
        dw = DESIGN_GRADE3.get(design, 0.25) if (r3.human_claim(claim) and not pre) else lv.design_weight(design, False)
        if against:
            prec, eff = ["power", null_power(rec.n_total, rec.comparison)], ["against", 1.0]
        else:
            prec = [rec.n_total, PRECLINICAL_PRECISION if pre else precision(rec.n_total)]
            full = effect_weight(rec, False) >= EFFECT_FULL_FROM - 1e-9
            eff = [rec.effect_class if full else "small or not stated", 1.0 if full else 0.5]
        return {"design": [design, dw], "precision": prec, "effect": eff,
                "comparison": [comp, 1.0 if rec.comparison == "between_groups" else 0.5],
                "context": [ctx, 0.5 if ctx == "adjacent" else 1.0]}
    return {"design": [r3.record_design(rec), lv.design_weight(r3.record_design(rec), r3.human_claim(claim) and not pre)],
            "precision": [rec.n_total, PRECLINICAL_PRECISION if (v34 and pre) else precision(rec.n_total)],
            "effect": ["against" if against else rec.effect_class, effect_weight(rec, against)],
            "comparison": [comp, lv.weight("comparison", comp)], "context": [ctx, lv.weight("context", ctx)]}


def strength(F: float, A: float, c: float = C_ANCHOR) -> tuple[float, float, float]:
    """(mean, 5%, 95%) of Beta(1 + cF, 1 + cA)."""
    from scipy.stats import beta
    a, b = 1 + c * F, 1 + c * A
    return a / (a + b), float(beta.ppf(0.05, a, b)), float(beta.ppf(0.95, a, b))


def non_refutation(F: float, A: float, c: float = C_ANCHOR) -> float:
    """v3.4: R = (1 + cF) / (1 + cF + cA); 1 when nothing is against."""
    return (1 + c * F) / (1 + c * F + c * A)


@dataclass
class V32Result:
    gate: str = "pass"
    P: float = 0.0
    P_lo: float = 0.0
    P_hi: float = 0.0
    I: float = 0.0
    V: float = 0.0
    scope: str = "local"
    links: dict[str, list[float]] = field(default_factory=dict)      # id -> [S, lo, hi, F, A]
    weakest: str = ""
    coverage: float = 0.0                                             # share of slots with data (reported)
    support_share: float = 0.0                                        # mean support of the slots (v3.3 indicator)
    chain_state: float = 0.0                                          # A: mean of 2S - 1 over the slots
    silent_share: float = 0.0                                         # G: slots read but with no stance and no record
    headroom_I: Optional[float] = None                                # v3.4: I if the experiment cut off every supported alternative

    def as_dict(self) -> dict:
        return asdict(self)


EMPTY_SLOTS = os.environ.get("EMPTY_SLOTS", "skip")       # v3.7 (user 2026-11-09, specs/empty-slots-2026-11-09.yaml): "skip"; "count" = v3.6


def evaluate(card: HypothesisCard, ver_claims: list[ClaimVerification],
             alt_verifications: Optional[dict[str, ClaimVerification]] = None, c: float = C_ANCHOR,
             fold: bool = False, neutral_unverified: bool = False, v34: bool = False, null_power: bool = False,
             v35: bool = False, v36: bool = False) -> V32Result:
    """v3.5 (2026-11-08, specs/link-scoring-2026-11-08.yaml) = v3.4 + a null weighted by its power; the profiles use the
    signed chain state (mean of 2S - 1 over the slots) instead of P and the support share."""
    global NULL_POWER, V36
    if v36:
        v35 = True
    if v35:
        v34, null_power = True, True
    NULL_POWER, V36 = null_power, v36
    try:
        return _evaluate(card, ver_claims, alt_verifications, c, fold, neutral_unverified, v34)
    finally:
        NULL_POWER, V36 = False, False


def _evaluate(card: HypothesisCard, ver_claims: list[ClaimVerification],
              alt_verifications: Optional[dict[str, ClaimVerification]], c: float,
              fold: bool, neutral_unverified: bool, v34: bool) -> V32Result:
    base = r3.evaluate(card, ver_claims, alt_verifications, variant=VARIANT_BASE)     # gate, scope, approval, flags
    res = V32Result(gate=base.gate, scope=base.scope)
    fold = fold or v34
    by_id = {cv.id: cv for cv in ver_claims}
    links = r3.chain(card)
    if not links:
        return res
    for cl in links:
        cv = by_id.get(cl.id)
        F = side_weight(cv.evidence if cv else [], cl, False, fold, v34)
        A = side_weight(cv.counterevidence if cv else [], cl, True, fold, v34)
        s, lo, hi = strength(F, A, c)
        s = link_point(F, A, c)                       # v3.6: the log-likelihood sum; the interval stays the Beta's (amount of data)
        if base.links.get(cl.id) == "moderate" and f"{cl.id}_established_by_approval" in base.flags:
            s, lo, hi = max(s, 5 / 6), max(lo, 5 / 6), max(hi, 5 / 6)
        res.links[cl.id] = [round(s, 4), round(lo, 4), round(hi, 4), round(F, 3), round(A, 3)]
    checked = {cl.id for cl in links if res.links[cl.id][3] + res.links[cl.id][4] > 0
               or f"{cl.id}_established_by_approval" in base.flags}
    if v34:
        tri_of = {k: [non_refutation(v[3], v[4], c)] * 3 for k, v in res.links.items()}
    else:
        tri_of = {k: ([1.0, 1.0, 1.0] if neutral_unverified and k not in checked else v[:3]) for k, v in res.links.items()}
    outs, primary = r3.outcome_group(card, links)
    tri = [1.0, 1.0, 1.0]
    run: list[list[float]] = []

    def take(vals: list[list[float]]):
        for k in range(3):
            prod = 1.0
            for v in vals:
                prod *= v[k]
            tri[k] *= prod ** (1 / len(vals))
    for cl in links + [None]:
        if cl is not None and cl.link == "pathway" and cl not in outs:
            run.append(tri_of[cl.id])
            continue
        if run:
            take(run)
            run = []
        if cl is None or cl in outs:
            continue
        take([tri_of[cl.id]])
    if outs:
        if primary is not None:
            take([tri_of[primary.id]])
        else:
            tri = [tri[k] * sum(tri_of[o.id][k] for o in outs) / len(outs) for k in range(3)]
    res.P, res.P_lo, res.P_hi = (round(x, 5) for x in tri)
    res.weakest = min(links, key=lambda x: res.links[x.id][0]).id
    slots, run_ = [], []
    for cl in links + [None]:
        if cl is not None and cl.link == "pathway" and cl not in outs:
            run_.append(cl.id)
            continue
        if run_:
            slots.append(run_)
            run_ = []
        if cl is not None and cl not in outs:
            slots.append([cl.id])
    if outs:
        slots.append([primary.id] if primary is not None else [o.id for o in outs])
    res.coverage = round(sum(1 for sl in slots if any(i in checked for i in sl)) / len(slots), 4) if slots else 0.0

    def slot_S(sl):
        if len(sl) > 1 and outs and sl[0] in {o.id for o in outs}:
            return sum(res.links[i][0] for i in sl) / len(sl)          # parallel outcomes without a primary: their mean
        return max(res.links[i][0] for i in sl)                         # a cascade: its best link
    # EMPTY_SLOTS = "skip" (v3.7, user 2026-11-09): a slot none of whose links has a counting record is left out of the
    # balance and the support share ("nothing known" is not averaged in; gaps show in coverage and the improvement list)
    sl_used = [sl for sl in slots if any(res.links[i][3] + res.links[i][4] > 0 for i in sl)] if EMPTY_SLOTS == "skip" else slots
    res.support_share = round(sum(max(0.0, 2 * (slot_S(sl) - 0.5)) for sl in sl_used) / len(sl_used), 4) if sl_used else 0.0
    res.chain_state = round(sum(2 * slot_S(sl) - 1 for sl in sl_used) / len(sl_used), 4) if sl_used else 0.0
    silent = [sl for sl in slots if all(res.links[i][3] + res.links[i][4] == 0 for i in sl)
              and any(by_id.get(i) is not None and by_id[i].no_stance for i in sl)]
    res.silent_share = round(len(silent) / len(slots), 4) if slots else 0.0
    total = 0.0
    total_all = 0.0
    supported = False
    for alt in card.proposed_alternatives:
        cv = (alt_verifications or {}).get(alt.id)
        a_claim = Claim(id=alt.id, subject=alt.subject, relation=alt.relation, object=alt.object, qualifiers=alt.qualifiers,
                        role="premise", source_span="")
        F = side_weight(cv.evidence if cv else [], a_claim, False, fold, v34)
        A = side_weight(cv.counterevidence if cv else [], a_claim, True, fold, v34)
        a = max(0.0, 2 * (link_point(F, A, c) - 0.5))
        d = max(lv.weight("discrimination", alt.on_positive), lv.weight("discrimination", alt.on_negative))
        supported |= a > 0
        total += a * d
        total_all += a
    if v34:                                               # 2026-11-08 (user): I on 0-1, no floor of 1/3
        res.I = round(min(1.0, total / r3.I_CAP), 4) if supported else 0.0
        res.headroom_I = round(min(1.0, total_all / r3.I_CAP), 4) if supported else 0.0
    else:
        res.I = round(1 / 3 + 2 / 3 * min(1.0, total / r3.I_CAP), 4) if supported else round(1 / 3, 4)
    res.V = round(res.P * res.I, 6) if res.gate == "pass" else 0.0
    return res

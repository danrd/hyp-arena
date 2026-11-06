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
established by approval) carries what is not checked, as a separate ASPID indicator.
"""
from __future__ import annotations

import math
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


def side_weight(recs: list[EvidenceRecord], claim: Claim, against: bool, fold: bool) -> float:
    if not fold:
        return sum(record_weight(r, claim, against) for r in recs)
    groups: dict[str, list[float]] = {}
    for r in recs:
        groups.setdefault(group_key(r), []).append(record_weight(r, claim, against))
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
            x = float(m.group(1))
            if kind == "ratio" and x > 0:
                d = abs(math.log(x)) * math.sqrt(3) / math.pi
            elif kind == "d":
                d = abs(x)
            break
    if d is None:
        return lv.weight("effect", rec.effect_class)
    return 0.25 + 0.75 * min(1.0, d / 0.8)


def record_weight(rec: EvidenceRecord, claim: Claim, against: bool) -> float:
    if not r3.usable(rec, VARIANT_BASE):
        return 0.0
    ctx = r3.context_level(rec)
    if ctx is None:
        return 0.0
    preclinical = claim.link in r3.PRECLINICAL_LINKS
    w = lv.design_weight(r3.record_design(rec), r3.human_claim(claim) and not preclinical)
    w *= precision(rec.n_total)
    w *= effect_weight(rec, against)
    w *= lv.weight("comparison", rec.comparison if rec.comparison != "unknown" else "none")
    w *= lv.weight("context", ctx)
    return w


def strength(F: float, A: float, c: float = C_ANCHOR) -> tuple[float, float, float]:
    """(mean, 5%, 95%) of Beta(1 + cF, 1 + cA)."""
    from scipy.stats import beta
    a, b = 1 + c * F, 1 + c * A
    return a / (a + b), float(beta.ppf(0.05, a, b)), float(beta.ppf(0.95, a, b))


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
    coverage: float = 0.0                                             # share of slots with data (v3.3 indicator)

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate(card: HypothesisCard, ver_claims: list[ClaimVerification],
             alt_verifications: Optional[dict[str, ClaimVerification]] = None, c: float = C_ANCHOR,
             fold: bool = False, neutral_unverified: bool = False) -> V32Result:
    base = r3.evaluate(card, ver_claims, alt_verifications, variant=VARIANT_BASE)     # gate, scope, approval, flags
    res = V32Result(gate=base.gate, scope=base.scope)
    by_id = {cv.id: cv for cv in ver_claims}
    links = r3.chain(card)
    if not links:
        return res
    for cl in links:
        cv = by_id.get(cl.id)
        F = side_weight(cv.evidence if cv else [], cl, False, fold)
        A = side_weight(cv.counterevidence if cv else [], cl, True, fold)
        s, lo, hi = strength(F, A, c)
        if base.links.get(cl.id) == "moderate" and f"{cl.id}_established_by_approval" in base.flags:
            s, lo, hi = max(s, 5 / 6), max(lo, 5 / 6), max(hi, 5 / 6)
        res.links[cl.id] = [round(s, 4), round(lo, 4), round(hi, 4), round(F, 3), round(A, 3)]
    checked = {cl.id for cl in links if res.links[cl.id][3] + res.links[cl.id][4] > 0
               or f"{cl.id}_established_by_approval" in base.flags}
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
    total = 0.0
    supported = False
    for alt in card.proposed_alternatives:
        cv = (alt_verifications or {}).get(alt.id)
        a_claim = Claim(id=alt.id, subject=alt.subject, relation=alt.relation, object=alt.object, qualifiers=alt.qualifiers,
                        role="premise", source_span="")
        F = side_weight(cv.evidence if cv else [], a_claim, False, fold)
        A = side_weight(cv.counterevidence if cv else [], a_claim, True, fold)
        a = max(0.0, 2 * (strength(F, A, c)[0] - 0.5))
        d = max(lv.weight("discrimination", alt.on_positive), lv.weight("discrimination", alt.on_negative))
        supported |= a > 0
        total += a * d
    res.I = round(1 / 3 + 2 / 3 * min(1.0, total / r3.I_CAP), 4) if supported else round(1 / 3, 4)
    res.V = round(res.P * res.I, 6) if res.gate == "pass" else 0.0
    return res

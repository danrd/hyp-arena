"""Novelty, leverage and the drift flag of method v3.4 (specs/v34-frontier-2026-11-07.yaml), computed by code from the saved
records, no model calls.

- N (ordinal, low to high): new_context < translation < analog < new_combination < new_link, the distance of the hypothesis
  to what was already asked before its date (records on either side count: a question already asked is not new);
- link_levels: the same ladder per link from its own records;
- literature_density: log10(1 + PubMed records on the intervention AND the outcome before the date), a candidate;
- leverage: how much support_share would rise if the bottleneck slot reached S = 5/6, times the mean support of the other
  slots (a chain of guesses has none); W_potential: the scope then;
- drift(parent, child): the evolution flag "moved towards the known" (shown, never excluding).
"""
from __future__ import annotations

import math
from typing import Optional

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import Claim, ClaimVerification, EvidenceRecord, HypothesisCard

LEVELS = ("new_context", "translation", "analog", "new_combination", "new_link")
LINK_LEVELS = ("new_context", "translation", "analog", "new_link")
S_TARGET = 5 / 6
A_TARGET = 2 * (S_TARGET - 0.5)


def evaluate(card: HypothesisCard, cvs: list[ClaimVerification], alts: Optional[dict] = None) -> r32.V32Result:
    return r32.evaluate(card, cvs, alts or {}, v34=True)


def _same_species(rec: EvidenceRecord, claim: Claim) -> bool:
    if rec.qualifiers_match.get("species") == "no":
        return False
    if r3.human_claim(claim):
        return r3.record_design(rec) not in ("cells", "animal")
    return r3.record_design(rec) != "cells"


def record_level(rec: EvidenceRecord, claim: Claim) -> Optional[str]:
    """The ladder level one usable record gives its claim, or None when it does not count."""
    if r32.record_weight(rec, claim, False, True) <= 0 and r32.record_weight(rec, claim, True, True) <= 0:
        return None
    im = rec.qualifiers_match.get("intervention_match", "exact")
    if im in ("class", "related_compound"):
        return "analog"
    return "new_context" if _same_species(rec, claim) else "translation"


def link_level(claim: Claim, cv: Optional[ClaimVerification]) -> str:
    recs = (cv.evidence + cv.counterevidence) if cv else []
    lv = [x for x in (record_level(r, claim) for r in recs) if x]
    return min(lv, key=LINK_LEVELS.index) if lv else "new_link"


def slots(card: HypothesisCard) -> tuple[list[list[str]], list[str]]:
    """(slots before the outcome, the outcome slot): a pathway cascade is one slot; parallel outcomes one slot (the primary)."""
    links = r3.chain(card)
    outs, primary = r3.outcome_group(card, links)
    pre, run = [], []
    for cl in links + [None]:
        if cl is not None and cl.link == "pathway" and cl not in outs:
            run.append(cl.id)
            continue
        if run:
            pre.append(run)
            run = []
        if cl is not None and cl not in outs:
            pre.append([cl.id])
    out = [primary.id] if primary is not None else [o.id for o in outs]
    return pre, out


def _slot_S(e: r32.V32Result, sl: list[str], is_out: bool) -> float:
    if is_out and len(sl) > 1:
        return sum(e.links[i][0] for i in sl) / len(sl)
    return max(e.links[i][0] for i in sl)


def novelty(card: HypothesisCard, cvs: list[ClaimVerification], e: Optional[r32.V32Result] = None) -> Optional[str]:
    e = e or evaluate(card, cvs)
    by = {c.id: c for c in cvs}
    claims = {c.id: c for c in r3.chain(card)}
    pre, out = slots(card)
    lv = [x for i in out for r in ((by[i].evidence + by[i].counterevidence) if i in by else [])
          if (x := record_level(r, claims[i]))]
    if lv:
        return min(lv, key=LINK_LEVELS.index)
    if not pre:
        return None
    supported = [any(e.links[i][3] > 0 for i in sl) and _slot_S(e, sl, False) > 0.5 for sl in pre]
    empty = [all(e.links[i][3] + e.links[i][4] == 0 for i in sl) for sl in pre]
    if all(supported):
        return "new_combination"
    if any(supported) and any(empty):
        return "new_link"
    return None


def link_levels(card: HypothesisCard, cvs: list[ClaimVerification]) -> dict[str, str]:
    by = {c.id: c for c in cvs}
    return {c.id: link_level(c, by.get(c.id)) for c in r3.chain(card)}


def leverage(card: HypothesisCard, cvs: list[ClaimVerification], e: Optional[r32.V32Result] = None) -> tuple[float, str, str]:
    """(leverage, W_potential, the bottleneck link ids joined by ','): (support_share if the weakest slot had S = 5/6, minus
    support_share now) x the mean support of the other slots; ties go to the slot nearer the outcome; 0 for a one-slot chain."""
    e = e or evaluate(card, cvs)
    pre, out = slots(card)
    all_slots = [(sl, False) for sl in pre] + ([(out, True)] if out else [])
    if not all_slots:
        return 0.0, e.scope, ""
    a = [max(0.0, 2 * (_slot_S(e, sl, o) - 0.5)) for sl, o in all_slots]
    k = min(range(len(a)), key=lambda j: (a[j], -j))
    rest = [x for j, x in enumerate(a) if j != k]
    # amendment 2026-11-07 (before any use, see the spec): the gain counts in proportion to how supported the rest of the chain
    # is, so a chain of guesses (or one link alone) has no leverage: only a supported chain held back by one link has
    gain = max(0.0, A_TARGET - a[k]) / len(all_slots) * (sum(rest) / len(rest) if rest else 0.0)
    sl = all_slots[k][0]
    return round(gain, 4), scope_with(card, cvs, set(sl)), ",".join(sl)


def scope_with(card: HypothesisCard, cvs: list[ClaimVerification], raised: set[str]) -> str:
    """The v3.1 scope rule with the links in `raised` taken as moderate."""
    base = r3.evaluate(card, cvs, None, variant=r32.VARIANT_BASE)
    links = r3.chain(card)
    level = {c.id: ("moderate" if c.id in raised and base.links.get(c.id) not in ("moderate", "strong") else base.links.get(c.id))
             for c in links}
    supported = [c for c in links if level[c.id] in ("weak", "moderate", "strong")]
    strong = [c for c in supported if level[c.id] in ("moderate", "strong")]
    if any(c.object.hallmark or c.subject.hallmark for c in strong):
        return "hallmark"
    if any(c.object.hallmark or c.subject.hallmark for c in supported):
        return "organ"
    if any(c.link in ("engagement", "pathway", "effect") or c.role == "mechanism" for c in supported):
        return "organ"
    return "local"


def outcome_term(card: HypothesisCard) -> str:
    from hyparena.card import trend_genetics as tg
    for lab in (card.pico.outcome.metric, card.decisive_experiment.primary_outcome,
                card.outcome_claim.object.label if card.outcome_claim else ""):
        lab = tg.clean_label(lab or "")
        if lab and lab.lower() not in ("unknown", "human", "humans") and len(tg.words(lab)) <= 6:
            return lab
    return ""


def literature_density(card: HypothesisCard, as_of: str) -> Optional[float]:
    """log10(1 + PubMed records on the intervention AND the outcome, from 1900 to the date); None when a term is missing."""
    from hyparena.card import trend_genetics as tg
    ti, to = tg.terms(card), outcome_term(card)
    if not ti or not to:
        return None
    ws = tg.words(to)
    q_out = f'"{to}"[tiab]' if len(ws) <= 1 else "(" + " AND ".join(f"{w}[tiab]" for w in ws) + ")"
    end = tg._windows(as_of)[0][1]
    for q in ti:
        n = tg.pubmed_count(f"({q}) AND {q_out}", "1900-01-01", end)
        if n > 0 or q == ti[-1]:
            return round(math.log10(1 + n), 4)
    return None


def _texts(card: HypothesisCard) -> dict[str, str]:
    return {c.id: f"{c.link}: {c.subject.label} — {c.relation} — {c.object.label}" for c in r3.chain(card)}


def drift(parent: tuple[HypothesisCard, list[ClaimVerification]], child: tuple[HypothesisCard, list[ClaimVerification]]) -> dict:
    """The evolution flag: N of the child below N of the parent (both known), a kept link at a lower level, or the parent's
    new link gone with no new link in the child."""
    (pc, pcv), (cc, ccv) = parent, child
    np_, nc = novelty(pc, pcv), novelty(cc, ccv)
    lp, lc = link_levels(pc, pcv), link_levels(cc, ccv)
    tp, tc = _texts(pc), _texts(cc)
    by_text_c = {v: k for k, v in tc.items()}
    reasons = []
    if np_ and nc and LEVELS.index(nc) < LEVELS.index(np_):
        reasons.append(f"N {np_} -> {nc}")
    for k, t in tp.items():
        if t in by_text_c and LINK_LEVELS.index(lc[by_text_c[t]]) < LINK_LEVELS.index(lp[k]):
            reasons.append(f"link «{t}» {lp[k]} -> {lc[by_text_c[t]]}")
    new_p = [k for k, v in lp.items() if v == "new_link"]
    if new_p and all(tp[k] not in by_text_c for k in new_p) and "new_link" not in lc.values():
        reasons.append("the parent's new link is gone and the child has none")
    return {"N": [np_, nc], "drift_to_known": bool(reasons), "reasons": reasons}

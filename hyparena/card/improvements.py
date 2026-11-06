"""The list of improvements of one hypothesis, computed by code from its v3.3 analysis (user decision 2026-11-06: the analysis
names the places to improve explicitly; evolution applies them, nothing else).

Each item:
    {"id", "cls": "rewrite" | "research", "type", "target", "what": (ru, en), "facts": [{"pmid", "quote", "side"}],
     "expected": {"indicators": {name: [now, after]}, "score": {profile: [now, after]}} or None when it cannot be computed}

rewrite  - can be fixed by rewriting the hypothesis or its experiment from facts already found (evolution applies these);
research - needs new data (a study, the trial's own paper); stays a recommendation.
"""
from __future__ import annotations

import copy
from typing import Optional

from hyparena.card import aspid_v3
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification, HypothesisCard

V33 = {"fold": True, "neutral_unverified": True}
ENDPOINT_UP = {"biomarker": "function", "patient_reported": "function"}
ADJ_KEYS = ("population", "age_at_start", "sex")


def evaluate(card: HypothesisCard, cvs: list[ClaimVerification], alts: dict) -> r32.V32Result:
    return r32.evaluate(card, cvs, alts, **V33)


def axes(e: r32.V32Result, headroom_I: Optional[float], extras: dict) -> tuple[dict, dict]:
    return ({"P": e.P, "scope": e.scope, "I": e.I, "headroom_I": headroom_I if headroom_I is not None else e.I, "gate": e.gate},
            {**extras, "support_share": e.support_share})


def scores(pairs: dict[str, tuple[dict, dict]], K: int = 4000) -> dict[str, dict[str, float]]:
    """Expected ASPID value of each entry under each profile (fixed scales: independent of the other entries)."""
    out: dict[str, dict[str, float]] = {k: {} for k in pairs}
    for prof in aspid_v3.load():
        agg = aspid_v3.rank(pairs, prof, K=K)
        for k in pairs:
            if agg and k in agg.expected:
                out[k][prof] = round(agg.expected[k], 3)
    return out


def _facts(recs, side: str, n: int = 2) -> list[dict]:
    return [{"pmid": r.record_id.replace("PMID:", ""), "quote": (r.quote or "")[:300], "side": side} for r in recs[:n]]


def items(card: HypothesisCard, cvs: list[ClaimVerification], alts: dict[str, ClaimVerification], extras: dict,
          headroom_I: Optional[float] = None, K: int = 4000) -> list[dict]:
    base = evaluate(card, cvs, alts)
    if base.gate != "pass":
        return []
    links = r3.chain(card)
    by = {c.id: c for c in cvs}
    variants: list[tuple[dict, r32.V32Result, dict]] = []          # (item, modified result, modified extras)

    def add(item: dict, e_mod: Optional[r32.V32Result], ext_mod: Optional[dict] = None):
        variants.append((item, e_mod, ext_mod if ext_mod is not None else extras))

    # rewrite: the experiment rules out the supported alternatives it leaves standing
    open_alts = []
    for alt in card.proposed_alternatives:
        cv = alts.get(alt.id)
        if cv is None:
            continue
        ac = r32.Claim(id=alt.id, subject=alt.subject, relation=alt.relation, object=alt.object, qualifiers=alt.qualifiers,
                       role="premise", source_span="")
        F = r32.side_weight(cv.evidence, ac, False, True)
        A = r32.side_weight(cv.counterevidence, ac, True, True)
        if r32.strength(F, A)[0] > 0.5 and "eliminated" not in (alt.on_positive, alt.on_negative):
            open_alts.append((alt, cv))
    if open_alts:
        c2 = card.model_copy(deep=True)
        ids = {a.id for a, _ in open_alts}
        for a in c2.proposed_alternatives:
            if a.id in ids:
                a.on_positive = "eliminated"
        add({"cls": "rewrite", "type": "experiment_alternatives", "target": ",".join(sorted(ids)),
             "what": ("изменить эксперимент так, чтобы он отсекал подкреплённые альтернативы: " + "; ".join(
                 f"{a.subject.label} — {a.object.label}" for a, _ in open_alts),
                      "change the experiment so that it rules out the supported alternatives: " + "; ".join(
                 f"{a.subject.label} — {a.object.label}" for a, _ in open_alts)),
             "facts": [f for _, cv in open_alts for f in _facts(cv.evidence, "for", 1)]}, evaluate(c2, cvs, alts))
    for cl in links:
        cv = by.get(cl.id)
        S, lo, hi, F, A = base.links[cl.id]
        if cv is None:
            continue
        # rewrite: a link the data are against
        if A > 0 and S < 0.5:
            cvs2 = [ClaimVerification(id=c.id, evidence=c.evidence, counterevidence=[]) if c.id == cl.id else c for c in cvs]
            add({"cls": "rewrite", "type": "rewrite_refuted_link", "target": cl.id,
                 "what": (f"переписать звено «{cl.subject.label} — {cl.object.label}»: данные против него (S {S:.2f}); "
                          "сузить его до условий, где есть данные «за», или заменить другим путём",
                          f"rewrite the link \"{cl.subject.label} — {cl.object.label}\": the data are against it (S {S:.2f}); narrow "
                          "it to where there are data for, or replace it with another path"),
                 "facts": _facts(cv.counterevidence, "against") + _facts(cv.evidence, "for", 1)}, evaluate(card, cvs2, alts))
        # rewrite: support only in an adjacent population
        adj = [r for r in cv.evidence if any(r.qualifiers_match.get(k) == "no" for k in ADJ_KEYS)
               and r32.record_weight(r, cl, False) > 0]
        if adj:
            cvs2 = []
            for c in cvs:
                if c.id != cl.id:
                    cvs2.append(c)
                    continue
                ev = []
                for r in c.evidence:
                    if r in adj:
                        r = r.model_copy(deep=True)
                        for k in ADJ_KEYS:
                            if r.qualifiers_match.get(k) == "no":
                                r.qualifiers_match[k] = "yes"
                    ev.append(r)
                cvs2.append(ClaimVerification(id=c.id, evidence=ev, counterevidence=c.counterevidence))
            e2 = evaluate(card, cvs2, alts)
            if e2.P > base.P + 0.01 or e2.support_share > base.support_share + 0.01:
                add({"cls": "rewrite", "type": "narrow_population", "target": cl.id,
                     "what": (f"сузить популяцию звена «{cl.subject.label} — {cl.object.label}» до той, где получены данные «за»",
                              f"narrow the population of the link \"{cl.subject.label} — {cl.object.label}\" to the one the data for come from"),
                     "facts": _facts(adj, "for")}, e2)
        # research: a weakly supported link
        if F > 0 and 0.5 <= S < 5 / 6:
            add({"cls": "research", "type": "support_link", "target": cl.id,
                 "what": (f"подкрепить звено «{cl.subject.label} — {cl.object.label}» (S {S:.2f}): нужно исследование крупнее или "
                          "надёжнее по дизайну", f"support the link \"{cl.subject.label} — {cl.object.label}\" (S {S:.2f}): a larger or "
                          "better-designed study is needed"),
                 "facts": _facts(cv.evidence, "for", 1)}, _with_strength(card, cvs, alts, cl.id, 5 / 6))
        # research: a link without data
        if F == 0 and A == 0:
            add({"cls": "research", "type": "check_link", "target": cl.id,
                 "what": (f"проверить звено «{cl.subject.label} — {cl.object.label}»: в литературе до даты оценки данных нет",
                          f"check the link \"{cl.subject.label} — {cl.object.label}\": no data in the literature up to the date"),
                 "facts": []}, _with_strength(card, cvs, alts, cl.id, 5 / 6))
    # rewrite: the mechanism is not written
    if len(links) <= 1:
        add({"cls": "rewrite", "type": "write_mechanism", "target": "",
             "what": ("выписать механизм: через какие мишени и пути вмешательство действует на исход, опираясь на найденные статьи",
                      "write the mechanism: through which targets and pathways the intervention acts on the outcome, from the papers found"),
             "facts": []}, None)
    # rewrite: a more clinical endpoint
    ep = extras.get("endpoint_clinical")
    if ep in ENDPOINT_UP:
        add({"cls": "rewrite", "type": "clinical_endpoint", "target": "",
             "what": ("выбрать первичную конечную точку ближе к клинике (функция вместо биомаркера или самоотчёта)",
                      "choose a primary endpoint closer to the clinic (function instead of a biomarker or a self-report)"),
             "facts": []}, base, {**extras, "endpoint_clinical": ENDPOINT_UP[ep]})
    # score the variants against the base, all at once (fixed scales: the entries do not affect each other)
    pairs = {"base": axes(base, headroom_I, extras)}
    for i, (_, e_mod, ext) in enumerate(variants):
        if e_mod is not None:
            pairs[f"v{i}"] = axes(e_mod, headroom_I, ext)
    sc = scores(pairs, K=K)
    out = []
    for i, (item, e_mod, ext) in enumerate(variants):
        item = {"id": f"i{i + 1}", **item}
        if e_mod is None:
            item["expected"] = None
        else:
            ind = {}
            for name, a, b in (("P", base.P, e_mod.P), ("I", base.I, e_mod.I), ("support_share", base.support_share, e_mod.support_share)):
                if abs(b - a) > 1e-4:
                    ind[name] = [round(a, 3), round(b, 3)]
            if ext.get("endpoint_clinical") != extras.get("endpoint_clinical"):
                ind["endpoint_clinical"] = [extras.get("endpoint_clinical"), ext.get("endpoint_clinical")]
            item["expected"] = {"indicators": ind, "score": {p: [sc["base"][p], sc[f"v{i}"][p]] for p in sc["base"]}}
        out.append(item)
    return out


def _with_strength(card, cvs, alts, link_id: str, S_target: float) -> r32.V32Result:
    """The result if one link had strength S_target (a synthetic record weight F with S(F, 0) = S_target)."""
    from hyparena.card.models import EvidenceRecord
    c = r32.C_ANCHOR
    F = (S_target * 2 - 1) / (c * (1 - S_target))                 # (cF + 1) / (cF + 2) = S  =>  F = (2S - 1) / (c (1 - S))
    have = {x.id for x in cvs}
    rec = EvidenceRecord(source="synthetic", record_id="SYNTH:1", lab_or_cohort="SYNTH:1", design="rct", n_total=300,
                         comparison="between_groups", effect_class="large", quote_role="finding",
                         qualifiers_match={"intervention_match": "exact"})
    cl = next(x for x in r3.chain(card) if x.id == link_id)
    w = r32.record_weight(rec, cl, False) or 1.0
    reps = max(1, round(F / w)) if w else 1
    recs = [rec.model_copy(update={"record_id": f"SYNTH:{k}", "lab_or_cohort": f"SYNTH:{k}"}) for k in range(reps)]
    cvs2 = [ClaimVerification(id=x.id, evidence=x.evidence + recs, counterevidence=x.counterevidence) if x.id == link_id else x
            for x in cvs]
    if link_id not in have:
        cvs2.append(ClaimVerification(id=link_id, evidence=recs))
    return evaluate(card, cvs2, alts)

"""Pool report as one HTML page: a snapshot of the site for one pool (user decision 2026-11-06).

    python -m hyparena.report_html prospective --n 60 --out REPORT.html

Built by code from the saved run, the frozen scores and the rules (no model call): fixed wording, only numbers and names
change, so two reports always read the same way. Layout: how to read (what the numbers mean) -> the table of all hypotheses
-> top 3 per profile -> one analysis per hypothesis (what lifts, what lowers, what would raise it; collapsed) -> appendices
(method in brief and glossary, the full breakdown of each mechanism chain with its records, provenance). Russian and English
in one page (a switch). Style tokens follow the site (docs/site/index.html). Reports on private hypotheses stay private.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
from collections import Counter
from pathlib import Path
from typing import Optional

from hyparena.card import aspid_v3
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification, HypothesisCard

PROFILE_NAMES = {"evidence": ("Доказательность", "Evidence"), "evolution": ("Потенциал развития", "Room to grow"),
                 "funding": ("Финансирование", "Funding"), "frontier": ("Фронтир", "Frontier")}
IND_NAMES = {
    "P": ("неопровергнутость механизма", "non-refutation of the mechanism"),
    "I": ("информативность эксперимента", "informativeness of the experiment"),
    "I_headroom": ("запас информативности", "room for a more informative experiment"),
    "W": ("размах механизма", "scope of the mechanism"),
    "feasibility": ("реализуемость", "feasibility"),
    "best_design_outcome": ("лучший дизайн по исходу", "best design for the outcome"),
    "independent_outcome": ("независимые источники по исходу", "independent sources for the outcome"),
    "against_share": ("доля данных «против»", "share of evidence against"),
    "endpoint_clinical": ("клиничность конечной точки", "how clinical the endpoint is"),
    "trend_pubmed": ("рост внимания в литературе", "rising attention in the literature"),
    "ai_role": ("роль ИИ", "role of AI"),
    "support_share": ("подтверждённость механизма", "how much of the mechanism is supported"),
    "chain_state": ("баланс доказательств", "evidence balance"),
    "N": ("новизна", "novelty"),
}
NOVELTY_NAMES = {"new_context": ("новый контекст", "new context"), "translation": ("перенос на другой вид", "translation"),
                 "analog": ("аналог", "analog"), "new_combination": ("новое сочетание", "new combination"),
                 "new_link": ("новое звено", "new link"), None: ("неизвестно", "unknown")}
LINK_NAMES = {"delivery": ("доставка", "delivery"), "engagement": ("действие на мишень", "target engagement"),
              "pathway": ("сигнальный путь", "pathway"), "effect": ("промежуточный эффект", "intermediate effect"),
              "outcome": ("исход", "outcome")}
SCOPE_NAMES = {"local": ("локальный", "local"), "organ": ("орган / система", "organ or system"),
               "hallmark": ("признак старения", "hallmark of ageing")}
ENDPOINT_NAMES = {"biomarker": ("биомаркер", "biomarker"), "patient_reported": ("самоотчёт", "patient-reported"),
                  "function": ("функция", "function"), "clinical_event": ("клиническое событие", "clinical event"), None: ("—", "—")}
TYPE_NAMES = {"drug/supplement": ("лекарство / добавка", "drug / supplement"), "behavioral": ("поведенческое", "behavioural"),
              "device": ("устройство", "device"), "other (exercise etc.)": ("другое (упражнения и пр.)", "other (exercise etc.)")}
AI_NAMES = {"none": ("нет", "none"), "analysis": ("анализ данных", "data analysis"), "in_the_loop": ("ИИ в цикле", "AI in the loop"),
            "intervention": ("ИИ — вмешательство", "AI is the intervention")}
SHORT = {"P": ("P", "P"), "I": ("I", "I"), "I_headroom": ("Запас I", "I room"), "W": ("Размах", "Scope"),
         "feasibility": ("Реализ.", "Feasib."), "best_design_outcome": ("Дизайн", "Design"), "independent_outcome": ("Источн.", "Sources"),
         "against_share": ("«Против»", "Against"), "endpoint_clinical": ("Кон. точка", "Endpoint"), "trend_pubmed": ("Тренд", "Trend"),
         "ai_role": ("ИИ", "AI"), "support_share": ("Подтв.", "Supported"), "chain_state": ("Состояние", "State"), "N": ("Новизна", "Novelty")}
DESIGN_NAMES = {"none": ("нет данных", "no data"), "cells": ("клетки", "cells"), "animal": ("животные", "animals"),
                "observational": ("наблюдательное", "observational"), "review": ("обзор", "review"),
                "non_randomised": ("нерандомиз.", "non-randomised"), "meta_analysis": ("метаанализ", "meta-analysis"), "rct": ("РКИ", "RCT")}
ORDINAL = {"W": ("local", "organ", "hallmark"), "endpoint_clinical": ("biomarker", "patient_reported", "function", "clinical_event"),
           "ai_role": ("none", "analysis", "in_the_loop", "intervention"),
           "best_design_outcome": aspid_v3.SPECS["best_design_outcome"].levels, "N": aspid_v3.SPECS["N"].levels}


TIPS = {
    "P": ("Неопровергнутость механизма, от 0 до 1 (v3.4; прежнее название — правдоподобие): насколько цепочка не опровергнута. 1 значит «данных против не найдено», а не «гипотеза верна». Звено без данных «против» — 1, данные «против» снижают его, данные «за» смягчают это снижение. Опору литературы показывает отдельная ось «подтверждённость», поэтому первая скромная статья по звену больше не снижает P.",
          "Non-refutation of the mechanism, 0 to 1 (v3.4; formerly plausibility): how far the chain is not refuted. 1 means \"nothing against was found\", not \"the hypothesis is true\". A link with no data against is 1; data against lower it, data for soften that. Support from the literature is the separate support axis, so a first modest paper on a link no longer lowers P."),
    "N": ("Новизна: насколько гипотеза далека от того, что уже спрашивали до даты оценки. Новый контекст (то же вмешательство и исход уже изучали на людях, в другой популяции или дозе) < перенос (только на другом виде) < аналог (только родственное соединение или класс) < новое сочетание (звенья известны по отдельности, цепочку целиком не проверяли) < новое звено. Неизвестно, если данных нет вовсе: отсутствие данных — не новизна. ⚠ Внешняя проверка (2026-11-08): второй читатель согласен слабо (κ 0.14) и ставит уровень ближе к известному в 21 из 37 испытаний — наша новизна завышена.",
          "Novelty: how far the hypothesis is from what was asked before the date. New context (the same intervention and outcome already studied in humans, another population or dose) < translation (only in another species) < analog (only a related compound or class) < new combination (the links are known one by one, the chain as a whole was not tested) < new link. Unknown when there are no data at all: absence of data is not novelty."),
    "I": ("Информативность эксперимента, от 0 до 1: сколько подкреплённых литературой альтернативных объяснений отсечёт заявленный эксперимент. 0 — ни одного. ⚠ Внешняя проверка (2026-11-08): d альтернатив с 2026-11-08 оценивается по тексту реестра (κ с внешним читателем 0.35 вместо 0.005 у прежней оценки); опора альтернатив a — по найденным статьям.",
          "Informativeness, 0 to 1: how many literature-supported alternative explanations the stated experiment rules out. 0: none."),
    "I_headroom": ("Запас информативности: какой была бы информативность, если бы эксперимент отсекал все подкреплённые альтернативы. Показывает, сколько можно выиграть, улучшив дизайн.",
                   "Room for informativeness: what it would be if the experiment ruled out every supported alternative; what a better design could add."),
    "W": ("Размах: как широко действует подтверждённая литературой часть механизма — локально, на орган или систему, на признак старения.",
          "Scope: how far the supported part of the mechanism reaches: local, an organ or system, a hallmark of ageing."),
    "feasibility": ("Реализуемость, от 0 до 1: среднее цены системы (клетки дешевле людей), длительности, плановой выборки и готовности вмешательства (одобрено или не вещество — 1, в испытаниях — 0.5).",
                    "Feasibility, 0 to 1: mean of the cost of the system (cells cheaper than people), duration, planned sample and readiness of the intervention (approved or not a compound 1, in trials 0.5)."),
    "best_design_outcome": ("Лучший дизайн среди исследований по исходу: от клеточного опыта до рандомизированного испытания (РКИ).",
                            "Best design among the studies of the outcome: from a cell study to a randomised trial (RCT)."),
    "independent_outcome": ("Число независимых источников по исходу: статьи одного испытания считаются одним источником.",
                            "Independent sources for the outcome: papers of one trial count as one source."),
    "against_share": ("Доля веса данных «против» во всей цепочке: чем меньше, тем лучше.",
                      "Share of the chain's evidence weight that is against: lower is better."),
    "endpoint_clinical": ("Насколько первичная конечная точка испытания близка к клиническому исходу: биомаркер < самоотчёт < функция < клиническое событие (падения, госпитализации, смерть).",
                          "How close the trial's primary endpoint is to a clinical outcome: biomarker < patient-reported < function < clinical event (falls, hospitalisation, death)."),
    "trend_pubmed": ("Рост внимания: публикации о вмешательстве за 3 года до оценки против 3 лет до них, за вычетом роста всего PubMed. 0 — как вся литература, 0.7 — примерно вдвое быстрее.",
                     "Rising attention: publications on the intervention in the 3 years before scoring vs the 3 before, net of PubMed's growth. 0 = like all literature, 0.7 = about twice as fast."),
    "chain_state": ("Баланс доказательств, от −1 до +1: среднее по звеньям величины 2S − 1. −1 — данные против звеньев, 0 — ничего не известно или «за» и «против» уравновешены, +1 — звенья подтверждены. Одна ось вместо неопровергнутости и подтверждённости: различает «опровергнуто» и «неизвестно». Нулевой результат маленького исследования весит по его мощности.",
                    "Evidence balance, −1 to +1: the mean over the links of 2S − 1. −1: data against the links; 0: nothing known, or for and against balanced; +1: the links are supported. One axis instead of non-refutation and support; tells refuted from unknown. A null of a small study weighs by its power."),
    "support_share": ("Подтверждённость механизма, от 0 до 1: средняя подтверждённость звеньев цепочки. Звено без данных или с данными только «против» — 0, умеренная поддержка — 0.67, сильная — около 1. Звенья без данных не снижают P, но снижают эту ось: гипотеза из одних догадок не получит высокое место.",
                      "How much of the mechanism is supported, 0 to 1: the mean support of the chain's links. A link without data or with data only against is 0, moderate support 0.67, strong near 1. Links without data do not lower P but lower this axis: a hypothesis made of guesses does not rank high."),
    "ai_role": ("Роль ИИ в гипотезе: нет / анализ данных / ИИ в цикле эксперимента / ИИ — само вмешательство; ставится только по дословной фразе текста.",
                "Role of AI: none / data analysis / AI in the experiment loop / AI is the intervention; set only from a verbatim phrase of the text."),
    "score": ("Ожидаемая оценка в профиле, от 0 до 1: среднее по 10 000 случайным наборам весов, совместимым с порядком важности профиля.",
              "Expected score under the profile, 0 to 1: the mean over 10,000 random weight sets compatible with the profile's order of importance."),
    "top5": ("Вероятность попасть в первую пятёрку пула по этому профилю: доля из 10 000 розыгрышей весов, где гипотеза оказалась в пятёрке. Показывает, насколько место устойчиво к выбору весов.",
             "Probability of being in the pool's top 5 under this profile: the share of 10,000 weight draws in which the hypothesis was in the top 5; how robust the place is to the choice of weights."),
    "place": ("Место по ожидаемой оценке (1 — лучшая).", "Place by the expected score (1 = best)."),
    "room": ("Запас улучшения в этом профиле: насколько вырастет ожидаемая оценка, если применить вместе все пункты «можно исправить формулировкой» из разбора гипотезы (эксперимент, отсекающий альтернативы; переписанное опровергнутое звено; суженная популяция; клиническая конечная точка). «Выписать механизм» заранее не считается — отмечено звёздочкой. ↓ — улучшение снижает новизну (сдвиг к известному). По запасу выбираются гипотезы для эволюции.",
             "Room to improve under this profile: how much the expected score would rise if every \"fixable by rewriting\" item of the analysis were applied together (an experiment ruling out the alternatives, a rewritten refuted link, a narrowed population, a clinical endpoint). \"Write the mechanism\" cannot be computed in advance: marked with an asterisk. ↓: the improvement lowers novelty (a move towards the known). Hypotheses for evolution are chosen by the room."),
    "S": ("Сила звена, от 0 до 1: 1 / (1 + e^(−λ(F − A))), «за» с плюсом, «против» с минусом; 0.5 — данных нет или поровну (узкий интервал — поровну); 0.83 — F = 0.6 без «против».",
          "Link strength, 0 to 1: 0.5 = no data; 0.83 = moderate support; about 0.5 with a narrow interval = data for and against balance."),
}


def tip(key: str, label: str) -> str:
    ru, en = TIPS.get(key) or GLOSSARY_EXTRA[key]
    return f'<span class="tip" tabindex="0" data-ru="{e(ru)}" data-en="{e(en)}">{label}</span>'


def e(x) -> str:
    return html.escape(str(x), quote=True)


def t(ru: str, en: str) -> str:
    return f'<span class="l-ru">{ru}</span><span class="l-en">{en}</span>'


def tn(pair) -> str:
    return t(e(pair[0]), e(pair[1]))


def fmt(x: Optional[float], d: int = 2) -> str:
    return "—" if x is None else f"{x:.{d}f}"


# ---------------------------------------------------------------- data

def roc_weights(tiers: list[list[str]]) -> dict[str, float]:
    """Expected weight of each indicator under an order of tiers: rank-order centroid over the tiers, split within a tier."""
    T = len(tiers)
    out = {}
    for i, tier in enumerate(tiers):
        w = sum(1 / k for k in range(i + 1, T + 1)) / T
        for ind in tier:
            out[ind] = w / len(tier)
    return out


def _num(ind: str, v):
    if v is None:
        return None
    if ind in ORDINAL:
        lv = ORDINAL[ind]
        return lv.index(v) / (len(lv) - 1) if v in lv else None
    if ind == "against_share":
        return -v
    return float(v)


def percentiles(vals: dict[str, Optional[float]]) -> dict[str, Optional[float]]:
    known = sorted(v for v in vals.values() if v is not None)
    if not known:
        return {h: None for h in vals}
    out = {}
    for h, v in vals.items():
        if v is None:
            out[h] = None
            continue
        below = sum(1 for x in known if x < v)
        same = sum(1 for x in known if x == v)
        out[h] = (below + 0.5 * same) / len(known)
    return out


def p_product(card: HypothesisCard, S: dict[str, float]) -> float:
    """P from link strengths, as rules_v32.evaluate combines them (pathway cascades as a geometric mean, parallel outcomes once)."""
    links = r3.chain(card)
    outs, primary = r3.outcome_group(card, links)
    P, run = 1.0, []
    for cl in links + [None]:
        if cl is not None and cl.link == "pathway" and cl not in outs:
            run.append(S[cl.id])
            continue
        if run:
            prod = 1.0
            for v in run:
                prod *= v
            P *= prod ** (1 / len(run))
            run = []
        if cl is None or cl in outs:
            continue
        P *= S[cl.id]
    if outs:
        P *= S[primary.id] if primary is not None else sum(S[o.id] for o in outs) / len(outs)
    return P


def build(run: dict, scores: dict, units: list[dict], texts: dict[str, str], meta: dict) -> dict:
    profiles = aspid_v3.load()
    unit = {u["id"]: u for u in units}
    hyps, values = {}, {}
    for h, r in run.items():
        it = r["items"][0]
        sc = scores.get(h, {})
        title = next((l[len("Title:"):].strip() for l in texts.get(h, "").splitlines() if l.startswith("Title:")), h)
        par = next((h[:-len(sfx)] for sfx in EVO_SUFFIXES.values() if h.endswith(sfx)), None)
        base = {"id": h, "parent": par, "evo_mode": unit.get(h, {}).get("evo_mode"), "new_after": unit.get(h, {}).get("new_after"), "title": title, "type": unit.get(h, {}).get("type"), "completion": unit.get(h, {}).get("primary_completion"),
                "outcome": it["outcome"], "scored": "P" in sc}
        if not it.get("card") or "P" not in sc:
            hyps[h] = base
            continue
        from hyparena.card import alternatives_d
        card = alternatives_d.apply(h, HypothesisCard.model_validate(it["card"]))
        cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
        alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
        from hyparena.card import improvements as imp
        from hyparena.card import novelty_v34 as nv
        res = imp.evaluate(card, cvs, alts)                                           # current rules (v3.6)
        labels = r3.evaluate(card, cvs, alts, variant="v3.1").links
        by = {c.id: c for c in cvs}
        chain = []
        for cl in r3.chain(card):
            cv = by.get(cl.id)
            recs = []
            for side, lst in (("for", cv.evidence if cv else []), ("against", cv.counterevidence if cv else [])):
                for rec in lst:
                    w = r32.current_weight(rec, cl, side == "against")
                    if w <= 0:
                        continue
                    recs.append({"side": side, "pmid": rec.record_id.replace("PMID:", ""), "w": round(w, 3),
                                 "f": r32.current_factors(rec, cl, side == "against"), "match": rec.qualifiers_match,
                                 "trial": rec.reports_trial, "primary": rec.primary_record,
                                 "design": r3.record_design(rec), "n": rec.n_total, "effect": rec.effect_reported or rec.effect_class,
                                 "quote": rec.quote, "group": r32.group_key(rec)})
            recs.sort(key=lambda x: -x["w"])
            S, lo, hi, F, A = res.links[cl.id]
            chain.append({"id": cl.id, "link": cl.link, "text": f"{cl.subject.label} — {cl.relation.replace('_', ' ')} — {cl.object.label}",
                          "hallmark": cl.object.hallmark, "S": S, "lo": lo, "hi": hi, "F": F, "A": A,
                          "label": labels.get(cl.id, "unverified"), "records": recs})
        alt_rows = []
        for alt in card.proposed_alternatives:
            cv = alts.get(alt.id)
            ac = r32.Claim(id=alt.id, subject=alt.subject, relation=alt.relation, object=alt.object, qualifiers=alt.qualifiers,
                           role="premise", source_span="")
            support = r32.current_support(cv.evidence if cv else [], cv.counterevidence if cv else [], ac)
            alt_rows.append({"id": alt.id, "text": f"{alt.subject.label} — {alt.relation.replace('_', ' ')} — {alt.object.label}",
                             "why": alt.rationale, "support": round(support, 3),
                             "on_positive": alt.on_positive, "on_negative": alt.on_negative})
        links = r3.chain(card)
        outs, primary = r3.outcome_group(card, links)
        in_p = {c.id for c in links if c not in outs} | ({primary.id} if primary is not None else {o.id for o in outs})
        for c in chain:
            c["in_P"] = c["id"] in in_p
            c["parallel_outcome"] = c["link"] == "outcome" and len(outs) > 1
            c["primary"] = primary is not None and c["id"] == primary.id
        for c in chain:
            c["checked"] = (c["F"] + c["A"]) > 0
        relevant = [c for c in chain if c["in_P"] and c["checked"]]
        weakest = min(relevant, key=lambda c: c["S"]) if relevant else None
        strongest = max(relevant, key=lambda c: c["S"]) if relevant else None
        N = nv.novelty(card, cvs, res)
        lev, _, bott = nv.leverage(card, cvs, res)
        raise_to, raise_link = None, (bott.split(",")[0] if lev > 0 else None)        # v3.4: support, not P, rises with data
        de = card.decisive_experiment
        hyps[h] = {**base, "plain": card.claim_plain, "P": res.P, "P_lo": res.P_lo, "P_hi": res.P_hi, "I": res.I, "V": res.V,
                   "scope": res.scope, "gate": res.gate, "chain": chain, "alternatives": alt_rows,
                   "weakest": weakest["id"] if weakest else None, "strongest": strongest["id"] if strongest else None,
                   "P_if_weakest_moderate": raise_to, "raise_link": raise_link, "support_share": res.support_share, "coverage": res.coverage,
                   "unchecked": [c["id"] for c in chain if not c["checked"]], "experiment": {"design": de.design, "endpoint": de.endpoint, "n": de.n_planned},
                   "endpoint_clinical": sc.get("endpoint_clinical"), "trend_pubmed": sc.get("trend_pubmed"), "ai_role": sc.get("ai_role"),
                   "ai_span": card.ai_role_span, "aspid": {p: sc.get(f"aspid_{p}") for p in profiles}, "N": N,
                   "N_pmid": nv.novelty_source(card, cvs),
                   "link_levels": nv.link_levels(card, cvs),
                   "flags": res_flags(it)}
        values[h] = {"P": res.P, "chain_state": res.chain_state, "I": res.I, "I_headroom": res.headroom_I if res.headroom_I is not None else it["v3"].get("headroom_I"), "W": res.scope, "support_share": res.support_share, "coverage": res.coverage, "N": N,
                     "endpoint_clinical": sc.get("endpoint_clinical"), "trend_pubmed": sc.get("trend_pubmed"), "ai_role": sc.get("ai_role"),
                     **{k: (it.get("extra") or {}).get(k) for k in ()}}
    # extras needed for profile contributions
    from hyparena.card import v3_extra
    for h in values:
        it = run[h]["items"][0]
        card = HypothesisCard.model_validate(it["card"])
        cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
        ext = v3_extra.extras(card, cvs, it["v3"], run[h]["meta"].get("as_of") or "")
        values[h].update({k: ext.get(k) for k in ("feasibility", "best_design_outcome", "independent_outcome", "against_share")})
    inds = sorted({i for p, _ in profiles.values() for tier in p.tiers for i in tier})
    pct = {ind: percentiles({h: _num(ind, values[h].get(ind)) for h in values}) for ind in inds}
    for h in values:
        hyps[h]["pct"] = {ind: pct[ind][h] for ind in inds}
        contrib = {}
        for name, (prof, _) in profiles.items():
            w = roc_weights(prof.tiers)
            parts = [(ind, w[ind] * (pct[ind][h] - 0.5)) for ind in w if pct[ind][h] is not None]
            parts.sort(key=lambda x: -x[1])
            contrib[name] = {"up": [p for p in parts if p[1] > 0.01][:2], "down": [p for p in parts[::-1] if p[1] < -0.01][:2]}
        hyps[h]["contrib"] = contrib
    scored = [h for h in hyps if hyps[h].get("P") is not None and hyps[h].get("gate") == "pass"]
    ax = {h: ({"P": hyps[h]["P"], "scope": hyps[h]["scope"], "I": hyps[h]["I"], "headroom_I": values[h]["I_headroom"], "gate": "pass"},
              {k: values[h].get(k) for k in ("feasibility", "best_design_outcome", "independent_outcome", "against_share",
                                              "endpoint_clinical", "trend_pubmed", "ai_role", "support_share", "chain_state", "N")}) for h in scored}
    ranks = {}
    for p in profiles:
        agg = aspid_v3.rank(ax, p, K=10000)
        for h in scored:
            hyps[h]["aspid"][p] = round(agg.expected[h], 4)
            hyps[h].setdefault("p_top5", {})[p] = round(agg.p_topk[h], 3)
        order = sorted(scored, key=lambda h: -hyps[h]["aspid"][p])
        ranks[p] = order
        for i, h in enumerate(order, 1):
            hyps[h].setdefault("rank", {})[p] = i
    from hyparena.card import improvements as imp
    for h in scored:
        hyps[h]["values"] = values[h]
        it = run[h]["items"][0]
        from hyparena.card import alternatives_d
        card = alternatives_d.apply(h, HypothesisCard.model_validate(it["card"]))
        cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
        alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
        ext = {k: values[h].get(k) for k in ("feasibility", "best_design_outcome", "independent_outcome", "against_share",
                                             "endpoint_clinical", "trend_pubmed", "ai_role")}
        an = imp.analyse(card, cvs, alts, {**ext, "N": values[h].get("N")}, values[h].get("I_headroom"))
        hyps[h]["improvements"], hyps[h]["room"] = an["items"], an["room"]
    for x in hyps.values():
        x.setdefault("rank", {})
        x.setdefault("p_top5", {})
    return {"meta": {**meta, "n": len(hyps), "n_scored": len(scored), "outcomes": dict(Counter(x["outcome"] for x in hyps.values())),
                     "profiles": {p: [list(t_) for t_ in prof.tiers] for p, (prof, _) in profiles.items()}},
            "hyps": hyps, "ranks": ranks}


def res_flags(it: dict) -> list[str]:
    return list((it.get("v3") or {}).get("flags") or [])


# ---------------------------------------------------------------- render

CSS = """
:root{--paper:#f4f6f3;--surface:#fff;--ink:#15201c;--muted:#5a6964;--line:#d9dfdb;--accent:#12695a;--accent-soft:#dcede7;
--ok:#2c7a4c;--bad:#b0402c;--warn:#a8740f;--idle:#7a8682;--ok-soft:#e1f0e6;--bad-soft:#f6e2dd;--warn-soft:#f5ead2;--idle-soft:#eaedeb;
--display:"Literata",Georgia,serif;--body:"Onest","Segoe UI",system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#0f1514;--surface:#162020;--ink:#e4ebe8;--muted:#98a6a1;
--line:#2a3633;--accent:#4db6a2;--accent-soft:#1b3430;--ok:#5dbd84;--bad:#e07a62;--warn:#d8a43f;--idle:#8b9893;--ok-soft:#173126;
--bad-soft:#3a211b;--warn-soft:#362a12;--idle-soft:#212b29;color-scheme:dark}}
:root[data-theme="dark"]{--paper:#0f1514;--surface:#162020;--ink:#e4ebe8;--muted:#98a6a1;--line:#2a3633;--accent:#4db6a2;
--accent-soft:#1b3430;--ok:#5dbd84;--bad:#e07a62;--warn:#d8a43f;--idle:#8b9893;--ok-soft:#173126;--bad-soft:#3a211b;--warn-soft:#362a12;
--idle-soft:#212b29;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--body);font-size:15px;line-height:1.55}
a{color:var(--accent)}h1,h2,h3{font-family:var(--display);font-weight:600;line-height:1.2;margin:0 0 .5em}h1{font-size:2rem}h2{font-size:1.5rem;margin-top:1.6em}
h3{font-size:1.1rem}.wrap{max-width:1120px;margin:0 auto;padding:0 16px 64px}.prose{max-width:70ch}.muted{color:var(--muted)}
.mono,code{font-family:var(--mono);font-size:.86em}.eyebrow{font-size:.8rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
header.top{position:sticky;top:0;z-index:5;background:var(--surface);border-bottom:1px solid var(--line)}
header.top .wrap{display:flex;gap:16px;align-items:center;padding:10px 16px;flex-wrap:wrap}header.top nav{display:flex;gap:14px;flex-wrap:wrap;font-size:.9rem}
header.top .sp{flex:1}button.sw{font:inherit;font-size:.85rem;border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:6px;padding:3px 8px;cursor:pointer}
html[data-lang="ru"] .l-en,html[data-lang="en"] .l-ru{display:none}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:12px 0}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.num{font-family:var(--mono);font-size:1.6rem}.kpi .lab{font-weight:600}.kpi p{margin:.3em 0 0;color:var(--muted);font-size:.9rem}
.tbl{width:100%;border-collapse:collapse;font-size:.88rem;background:var(--surface)}.tbl th,.tbl td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.tbl th{background:var(--surface);cursor:pointer;white-space:nowrap}.tbl td.title{min-width:240px}.tbl td.n{font-family:var(--mono);text-align:right;white-space:nowrap}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
.bar{display:inline-block;height:8px;border-radius:4px;background:var(--accent);vertical-align:middle}
.barbox{display:inline-block;width:70px;height:8px;border-radius:4px;background:var(--idle-soft);margin-right:6px;vertical-align:middle;position:relative}
.barbox .iv{position:absolute;top:0;height:8px;background:var(--accent-soft)}.barbox .pt{position:absolute;top:-2px;width:3px;height:12px;background:var(--accent)}
details{background:var(--surface);border:1px solid var(--line);border-radius:10px;margin:8px 0}details>summary{cursor:pointer;padding:10px 14px;list-style:none}
details>summary::-webkit-details-marker{display:none}details>summary::before{content:"▸ ";color:var(--muted)}details[open]>summary::before{content:"▾ "}
details .body{padding:0 16px 14px}details.sub{border:0;background:transparent;margin:6px 0}details.sub>summary{padding:4px 0}.chip{display:inline-block;border-radius:999px;padding:1px 8px;font-size:.8rem;background:var(--idle-soft);margin:0 4px 4px 0}.chip.bad{background:var(--bad-soft);color:var(--bad)}
.ok{background:var(--ok-soft)}.bad{background:var(--bad-soft)}.warn{background:var(--warn-soft)}
.chain{display:flex;flex-wrap:wrap;gap:6px;align-items:stretch;margin:8px 0}.link{border:1px solid var(--line);border-radius:8px;padding:6px 8px;min-width:150px;max-width:260px;font-size:.85rem}
.arrow{align-self:center;color:var(--muted)}.link .s{font-family:var(--mono)}
.up{color:var(--ok)}.down{color:var(--bad)}blockquote{margin:4px 0;padding-left:10px;border-left:3px solid var(--line);color:var(--muted);font-size:.85rem}
.tip{border-bottom:1px dotted var(--muted);cursor:help;position:relative}
a.rec.tip{border-bottom:1px solid var(--line)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.tabs button{font:inherit;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:4px 12px;cursor:pointer}
.tabs button[aria-selected="true"]{background:var(--accent);color:var(--surface);border-color:var(--accent)}
.ptab[hidden]{display:none}.cols{display:flex;gap:10px;flex-wrap:wrap;font-size:.85rem;margin:6px 0 8px;color:var(--muted)}.cols label{white-space:nowrap;cursor:pointer}
.hidecol{display:none}.pager{display:flex;gap:8px;align-items:center;margin:8px 0;font-size:.9rem}.pager button{font:inherit;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:6px;padding:2px 10px;cursor:pointer}
.tools{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:6px 0;font-size:.9rem}.tools input,.tools select{font:inherit;padding:3px 6px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink)}
tr.lead td:first-child{box-shadow:inset 3px 0 var(--accent)}.star{color:var(--accent);font-weight:600}
.steps{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:10px 0}.steps .st{border:1px solid var(--line);background:var(--surface);border-radius:8px;padding:6px 10px;font-size:.88rem;max-width:230px}
header.band{background:var(--accent);color:#fff}header.band .wrap{padding:12px 16px 0}header.band h1{color:#fff;font-size:1.5rem;margin:.3em 0 .5em}
header.band .bar1{display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:.85rem}header.band .badge{background:rgba(255,255,255,.15);border-radius:4px;padding:2px 8px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;font-size:.75rem}
header.band .meta{opacity:.85}header.band .sp{flex:1}header.band button.sw{background:transparent;color:#fff;border-color:rgba(255,255,255,.4)}
.vtabs{display:flex;gap:6px;flex-wrap:wrap}.vtabs button{font:inherit;font-size:.92rem;border:0;border-radius:8px 8px 0 0;padding:8px 14px;cursor:pointer;background:rgba(255,255,255,.12);color:#fff}
.vtabs button[aria-selected="true"]{background:var(--paper);color:var(--ink)}.view[hidden]{display:none}
.pill{display:inline-block;background:var(--warn-soft);border-radius:8px;padding:6px 12px;text-decoration:none;color:var(--ink);font-weight:500}
.tbl.links td{font-size:.84rem}.recs{max-width:420px}.rec{display:inline-block;border-radius:6px;padding:1px 6px;margin:0 4px 4px 0;font-size:.78rem;text-decoration:none;color:var(--ink);border:1px solid var(--line)}
.rec.ok{background:var(--ok-soft)}.rec.bad{background:var(--bad-soft)}.pad{padding:1px 5px;border-radius:4px}
#tt{position:fixed;z-index:100;max-width:min(380px,90vw);background:var(--ink);color:var(--paper);font:400 .82rem/1.45 var(--body);padding:8px 10px;border-radius:8px;pointer-events:none;display:none;box-shadow:0 4px 16px rgba(0,0,0,.25)}
dl.gl{display:grid;grid-template-columns:minmax(140px,220px) 1fr;gap:6px 14px;margin:0}dl.gl dt{font-weight:600}dl.gl dd{margin:0;color:var(--muted)}
@media (max-width:640px){dl.gl{grid-template-columns:1fr}}
@media print{header.top{position:static}details{break-inside:avoid}details:not([open])>.body{display:block}}
"""

JS = """
function setLang(l){document.documentElement.dataset.lang=l;try{localStorage.setItem('rep-lang',l)}catch(e){}}
function setTheme(){const r=document.documentElement;r.dataset.theme=r.dataset.theme==='dark'?'light':'dark'}
try{const l=localStorage.getItem('rep-lang');if(l)document.documentElement.dataset.lang=l}catch(e){}
document.querySelectorAll('table.sortable').forEach(tb=>{tb.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
 const rows=[...tb.tBodies[0].rows];const asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
 rows.sort((a,b)=>{const x=a.cells[i].dataset.v??a.cells[i].innerText,y=b.cells[i].dataset.v??b.cells[i].innerText;
  const nx=parseFloat(x),ny=parseFloat(y);const c=(!isNaN(nx)&&!isNaN(ny))?nx-ny:String(x).localeCompare(String(y));return asc?c:-c});
 rows.forEach(r=>tb.tBodies[0].appendChild(r))}))});
function cols(cb){const box=cb.closest('.ptab');box.querySelectorAll('[data-c="'+cb.dataset.c+'"]').forEach(el=>{if(el.tagName!=='INPUT')el.classList.toggle('hidecol',!cb.checked)})}
document.querySelectorAll('.cols input').forEach(cols);
const PAGE=15;
function refresh(tb){const q=(document.getElementById('fq').value||'').toLowerCase(),ty=document.getElementById('ftype').value;
 const rows=[...tb.tBodies[0].rows];const ok=rows.filter(r=>(!ty||r.dataset.type===ty)&&(!q||r.dataset.q.includes(q)));
 const pages=Math.max(1,Math.ceil(ok.length/PAGE));let pg=Math.min(+(tb.dataset.page||0),pages-1);tb.dataset.page=pg;
 rows.forEach(r=>r.style.display='none');ok.slice(pg*PAGE,pg*PAGE+PAGE).forEach(r=>r.style.display='');
 const pi=tb.parentElement.parentElement.querySelector('.pinfo');if(pi)pi.textContent=(pg+1)+' / '+pages+' · '+ok.length}
function page(btn,d){const box=btn.closest('.ptab');const tb=box.querySelector('table');tb.dataset.page=Math.max(0,(+tb.dataset.page||0)+d);refresh(tb)}
function showProfile(p){document.querySelectorAll('.tabs button').forEach(b=>b.setAttribute('aria-selected',b.dataset.p===p?'true':'false'));
 document.querySelectorAll('.ptab').forEach(d=>d.hidden=d.dataset.p!==p);const tb=document.querySelector('.ptab[data-p="'+p+'"] table');tb.dataset.page=0;refresh(tb)}
['fq','ftype'].forEach(id=>{const el=document.getElementById(id);if(el)el.addEventListener('input',()=>{document.querySelectorAll('.ptab table').forEach(tb=>{tb.dataset.page=0;refresh(tb)})})});
document.querySelectorAll('.ptab table').forEach(refresh);
document.querySelectorAll('table.sortable th').forEach(th=>th.addEventListener('click',()=>setTimeout(()=>refresh(th.closest('table')),0)));
function showView(v){document.querySelectorAll('.vtabs button').forEach(b=>b.setAttribute('aria-selected',b.dataset.view===v?'true':'false'));
 document.querySelectorAll('section.view').forEach(s=>s.hidden=s.dataset.view!==v);try{sessionStorage.setItem('rep-view',v)}catch(e){}}
function viewOf(el){const s=el&&el.closest('section.view');return s?s.dataset.view:null}
function go(hash){const el=document.getElementById(hash.slice(1));if(!el)return;const v=viewOf(el);if(v)showView(v);
 let d=el.tagName==='DETAILS'?el:el.closest('details');while(d){d.open=true;d=d.parentElement&&d.parentElement.closest('details')}
 setTimeout(()=>el.scrollIntoView({block:'start'}),0)}
document.addEventListener('click',ev=>{const a=ev.target.closest('a[href^="#"]');if(!a)return;const h=a.getAttribute('href');
 if(['#help','#evo','#rank','#src','#hyp'].includes(h)){ev.preventDefault();showView(h.slice(1));return}
 if(document.getElementById(h.slice(1))){ev.preventDefault();go(h);history.replaceState(null,'',h)}});
function openAll(o){document.querySelectorAll('section.view[data-view="hyp"] details').forEach(d=>d.open=o)}
function srcFilter(){const q=(document.getElementById('sq').value||'').toLowerCase();document.querySelectorAll('#srct tbody tr').forEach(r=>r.style.display=!q||r.dataset.q.includes(q)?'':'none')}
const TT=document.getElementById('tt');
function ttShow(el){const l=document.documentElement.dataset.lang||'ru';const txt=el.getAttribute('data-'+l)||el.getAttribute('data-ru');if(!txt)return;
 TT.textContent=txt;TT.style.display='block';const r=el.getBoundingClientRect();const w=TT.offsetWidth,hh=TT.offsetHeight;
 let x=Math.min(Math.max(8,r.left),window.innerWidth-w-8),y=r.bottom+6;if(y+hh>window.innerHeight-8)y=Math.max(8,r.top-hh-6);TT.style.left=x+'px';TT.style.top=y+'px'}
document.addEventListener('mouseover',ev=>{const el=ev.target.closest('.tip');if(el)ttShow(el)});
document.addEventListener('mouseout',ev=>{const el=ev.target.closest('.tip');if(el&&!el.contains(ev.relatedTarget))TT.style.display='none'});
document.addEventListener('focusin',ev=>{const el=ev.target.closest('.tip');if(el)ttShow(el)});document.addEventListener('focusout',()=>TT.style.display='none');
window.addEventListener('scroll',()=>TT.style.display='none',{passive:true});
(()=>{let v='rank';try{v=sessionStorage.getItem('rep-view')||'rank'}catch(e){}if(location.hash&&document.getElementById(location.hash.slice(1)))go(location.hash);else showView(v)})();
"""


ITEM_CLS = {"rewrite": ("Можно исправить формулировкой", "Fixable by rewriting"),
            "research": ("Нужны новые данные", "Needs new data")}


def render_items(items: list[dict], profs: list[str], room: Optional[dict] = None) -> str:
    """The improvement list of one hypothesis (hyparena/card/improvements.py), in two groups, each item with its expected
    effect on the indicators and on the score under each profile."""
    if not items:
        return ""
    gains = [(v[1] - v[0], p) for i in items if i.get("expected") for p, v in i["expected"]["score"].items() if p in PROFILE_NAMES]
    g = max(gains) if gains else None
    n_fix = sum(1 for i in items if i["cls"] == "rewrite")
    summary = (t("Что поднимет оценку", "What would raise it") + f' <span class="muted" style="font-size:.85rem">· ' +
               t(f"пунктов: {len(items)}, исправимых формулировкой: {n_fix}", f"items: {len(items)}, fixable by rewriting: {n_fix}") +
               (f' · {t("лучший","best")} {g[0]:+.2f} ({tn(PROFILE_NAMES[g[1]])})' if g and g[0] > 0 else "") + '</span>')
    out = [f'<details class="sub"><summary><b>{summary}</b></summary><div class="body"><p class="muted" style="font-size:.85rem">' +
           t("Перечень считает код; «ожидаемо» — если пункт выполнен.", "Computed by code; \"expected\" if the item is done.") + '</p>']
    if room and room.get("applied"):
        n0, n1 = room.get("N", [None, None])
        out.append('<p style="font-size:.9rem"><b>' + t("Запас улучшения", "Room to improve") + '</b> ' +
                   t("(все исправимые пункты вместе): ", "(all fixable items together): ") + " · ".join(
                       f'{tn(PROFILE_NAMES[p])} {v[1] - v[0]:+.3f}' for p, v in room["score"].items() if p in PROFILE_NAMES) +
                   (f'; {t("новизна","novelty")} {tn(NOVELTY_NAMES.get(n0, NOVELTY_NAMES[None]))} → {tn(NOVELTY_NAMES.get(n1, NOVELTY_NAMES[None]))}' if n0 != n1 else "") +
                   (f'<br><span class="muted">{t("не посчитано заранее: выписать механизм", "not computed in advance: write the mechanism")}</span>' if room.get("not_computed") else "") + '</p>')
    for cls in ("rewrite", "research"):
        group = [i for i in items if i["cls"] == cls]
        if not group:
            continue
        out.append(f'<p style="margin:.6em 0 .2em"><b>{tn(ITEM_CLS[cls])}</b></p><ul>')
        for i in group:
            exp = ""
            if i.get("expected"):
                def val(k, v):
                    if k == "endpoint_clinical":
                        return tn(ENDPOINT_NAMES.get(v, (str(v),) * 2))
                    if k == "N":
                        return tn(NOVELTY_NAMES.get(v, NOVELTY_NAMES[None]))
                    return fmt(v)
                ind = ", ".join(f'{tn(SHORT.get(k, (k, k)))} {val(k, v[0])} → {val(k, v[1])}' for k, v in i["expected"]["indicators"].items())
                sc = " · ".join(f'{tn(PROFILE_NAMES[p])} {"+" if v[1] - v[0] >= 0 else ""}{v[1] - v[0]:.2f}'
                                for p, v in i["expected"]["score"].items() if p in PROFILE_NAMES)
                exp = (f'<br><span class="muted" style="font-size:.85rem">{t("ожидаемо","expected")}: <span class="mono">{ind or "—"}</span>; '
                       f'{t("оценка","score")}: {sc}</span>')
            else:
                exp = f'<br><span class="muted" style="font-size:.85rem">{t("эффект заранее не рассчитать: зависит от того, что найдётся","the effect cannot be computed in advance: it depends on what is found")}</span>'
            facts = "".join(f'<blockquote><a href="https://pubmed.ncbi.nlm.nih.gov/{e(f["pmid"])}/" target="_blank" rel="noopener">{e(f["pmid"])}</a> '
                            f'({t("за","for") if f["side"] == "for" else t("против","against")}): {e(f["quote"][:220])}</blockquote>' for f in i.get("facts", [])[:2])
            facts_html = (f'<details class="sub"><summary class="muted" style="font-size:.85rem">{t("факты","facts")} ({len(i.get("facts", [])[:2])})</summary>{facts}</details>'
                          if facts else "")
            out.append(f'<li><span class="mono muted">{e(i["id"])}</span> {t(e(i["what"][0]), e(i["what"][1]))}{exp}{facts_html}</li>')
        out.append('</ul>')
    out.append('</div></details>')
    return "".join(out)


def render_evolution(evo: dict, H: dict, profs: list[str]) -> str:
    """Section "Evolution": parent -> improved version, the change of every indicator and of the score under each profile,
    what was applied and on which facts, the expected change of each item against the change obtained."""
    pairs = [(u, p) for u, p in evo.items() if p.get("compare")]
    skipped = [(u, p) for u, p in evo.items() if not p.get("compare")]
    out = [f'<h2 id="evo">{t("Эволюция: улучшенные версии", "Evolution: improved versions")}</h2><p class="prose muted">' + t(
        "Два режима, названы раздельно. <b>Доработанная версия</b>: применены только пункты «можно исправить формулировкой» из "
        "разбора; новые части родителя должны остаться — версия, сдвинутая к известному, возвращается писателю с причиной. "
        "<b>Свободная эволюция</b>: писатель меняет всё под выбранный профиль и называет статьи, на которые опирается (они "
        "засчитываются, только если их нашёл проверяющий до даты среза); сдвиг к известному помечается, но не запрещается; версия, "
        "далёкая от родителя, помечена «новая гипотеза после». Новых доказательств эволюция не создаёт, а улучшение оценивает тот же "
        "проверяющий, по находкам которого оно написано: рост оценки — подсказка, что менять, а не доказательство.",
        "Two modes, named apart. <b>Tuned version</b>: only the \"fixable by rewriting\" items of the analysis are applied; the "
        "parent's new parts must stay, and a version that moved towards the known goes back to the writer with the reason. "
        "<b>Free evolution</b>: the writer changes anything for the chosen profile and names the papers it relies on (they count "
        "only if the verifier finds them before the cut-off); a move towards the known is flagged, not forbidden; a version far "
        "from the parent is marked \"new hypothesis after\". Evolution makes no new evidence, and the improvement is scored by the "
        "verifier whose findings it was written from: a rise is a hint of what to change, not proof.") + '</p>']
    def base_id(u):
        return next((u[:-len(x)] for x in EVO_SUFFIXES.values() if u.endswith(x)), u)
    def mode_label(p):
        return t("свободная", "free") if p.get("mode") == "free" else t("доработка", "tuning")
    if pairs:
        out.append('<div class="scroll"><table class="tbl"><thead><tr><th>' + t("Гипотеза", "Hypothesis") + '</th><th>' +
                   t("Режим и пункты", "Mode and items") + '</th><th>P</th><th>I</th><th>' + tn(SHORT["support_share"]) + '</th><th>' +
                   tn(SHORT["N"]) + '</th>' +
                   "".join(f'<th>{tn(PROFILE_NAMES[p])}</th>' for p in profs) + '</tr></thead><tbody>')
        def nov(c):
            a, b = (c.get("drift") or {}).get("N", [None, None])
            s_ = f'{tn(NOVELTY_NAMES.get(a, NOVELTY_NAMES[None]))} → {tn(NOVELTY_NAMES.get(b, NOVELTY_NAMES[None]))}'
            if (c.get("drift") or {}).get("drift_to_known"):
                s_ += '<br><span class="chip bad">' + tip("drift", t("сдвиг к известному", "moved towards the known")) + '</span>'
            return s_
        for u, p in pairs:
            c = p["compare"]
            def d(a, b):
                if a is None or b is None or isinstance(a, str):
                    return f'{e(a)} → {e(b)}'
                cls = "up" if b > a + 1e-3 else "down" if b < a - 1e-3 else "muted"
                return f'<span class="{cls}">{fmt(a)} → {fmt(b)}</span>'
            out.append(f'<tr><td class="title"><a href="#ev-{e(u)}">{e(H.get(base_id(u), {}).get("title", u)[:80])}</a><br><span class="muted mono">{e(u)}</span></td>'
                       f'<td class="mono">{mode_label(p)}<br>{e(", ".join(p.get("applied", [])))}</td>'
                       f'<td class="n">{d(*c["indicators"]["P"])}</td><td class="n">{d(*c["indicators"]["I"])}</td>'
                       f'<td class="n">{d(*c["indicators"]["support_share"])}</td>' +
                       f'<td>{nov(c)}</td>' +
                       "".join(f'<td class="n">{d(*c["score"].get(pr, [None, None]))}</td>' for pr in profs) + '</tr>')
        out.append('</tbody></table></div>')
        by_type: dict = {}
        for u, p in pairs:
            for i in p["items"]:
                if i["id"] in p.get("applied", []):
                    by_type.setdefault(i["type"], []).append(p["compare"]["score"].get(profs[0], [0, 0]))
        if by_type:
            out.append('<p class="muted" style="font-size:.88rem">' + t("Средний сдвиг оценки (", "Mean change of the score (") +
                       tn(PROFILE_NAMES[profs[0]]) + t(") по видам применённых пунктов: ", ") by kind of applied item: ") + "; ".join(
                f'{e(k)} {sum(b - a for a, b in v) / len(v):+.3f} (n {len(v)})' for k, v in sorted(by_type.items())) + '</p>')
        for u, p in pairs:
            c = p["compare"]
            out.append(f'<details id="ev-{e(u)}"><summary>{e(H.get(base_id(u), {}).get("title", u)[:110])} <span class="muted mono">{e(u)}</span></summary><div class="body">')
            out.append('<p><b>' + t("Что применено и что изменилось", "What was applied and what changed") + '</b></p><ul>')
            ch = {x.get("item"): x.get("what_changed", "") for x in p.get("changes", [])}
            for i in p["items"]:
                if i["id"] not in p.get("applied", []):
                    continue
                exp = i.get("expected")
                exp_s = " · ".join(f'{tn(PROFILE_NAMES[pr])} {v[1] - v[0]:+.2f}' for pr, v in (exp or {}).get("score", {}).items() if pr in PROFILE_NAMES)
                out.append(f'<li><span class="mono muted">{e(i["id"])}</span> {t(e(i["what"][0]), e(i["what"][1]))}<br>'
                           f'<span class="muted" style="font-size:.85rem">{t("в тексте: ","in the text: ")}{e(ch.get(i["id"], "—"))}<br>'
                           f'{t("ожидалось: ","expected: ")}{exp_s or t("не рассчитывалось","not computed")}</span></li>')
            out.append('</ul><p class="muted" style="font-size:.88rem">' + t("Получено: ", "Obtained: ") + " · ".join(
                f'{tn(PROFILE_NAMES[pr])} {(v[1] or 0) - (v[0] or 0):+.2f}' for pr, v in c["score"].items() if pr in PROFILE_NAMES) + '</p>')
            dr = c.get("drift") or {}
            ks = dr.get("known_share")
            if ks:
                out.append('<p class="muted" style="font-size:.88rem">' + t("Доля звеньев с опорой в литературе до даты среза: ", "Share of links with support before the cut-off: ") +
                           f'{fmt(ks[0])} → {fmt(ks[1])}' + (t(" — версия собрана из уже известных кусков сильнее родителя", " — the version is built from known pieces more than the parent") if ks[1] > ks[0] + 0.25 else "") + '</p>')
            if p.get("mode") == "free":
                out.append('<p class="muted" style="font-size:.88rem">' + t("Названо статей: ", "Papers named: ") + f'{len(p.get("cited_pmids", []))}; ' +
                           t("найдено проверяющим: ", "found by the verifier: ") + f'{len(p.get("cited_found", []))}; ' + t("расстояние от родителя: ", "distance from the parent: ") + f'{fmt(p.get("distance"))}</p>')
            if p.get("mode", "tune") == "tune" and p.get("attempts", 1) > 1:
                out.append('<p class="muted" style="font-size:.88rem">' + t("Попыток: ", "Attempts: ") + f'{p["attempts"]}' +
                           (t(" (первая была сдвинута к известному и возвращена писателю)", " (the first moved towards the known and was sent back)") if p.get("constraint_kept") else t(" — ограничение новизны не удалось выдержать, версия оставлена с флагом", " — the novelty constraint could not be kept, the version stays with the flag")) + '</p>')
            if dr.get("drift_to_known"):
                out.append('<p class="down"><b>' + t("Сдвиг к известному: ", "Moved towards the known: ") + '</b>' + e("; ".join(dr.get("reasons", []))) +
                           '<br><span class="muted" style="font-size:.85rem">' + t("Версия остаётся в рейтинге; её новизна ниже, и это снижает оценку там, где новизна — показатель профиля.",
                                                                                  "The version stays in the ranking; its novelty is lower, which lowers its score where novelty is an indicator of the profile.") + '</span></p>')
            L = c["links"]
            if L["added"] or L["removed"]:
                out.append('<p><b>' + t("Звенья механизма", "Mechanism links") + '</b></p><ul>' +
                           "".join(f'<li class="up">+ {e(x["text"])} (S {fmt(x["S"])}{"" if x["records"] else t(", данных нет", ", no data")})</li>' for x in L["added"]) +
                           "".join(f'<li class="down">− {e(x["text"])} (S {fmt(x["S"])})</li>' for x in L["removed"]) + '</ul>')
            out.append(f'<details><summary>{t("Текст улучшенной версии", "Text of the improved version")}</summary><div class="body"><pre style="white-space:pre-wrap;font-size:.85rem">{e(p.get("child_text", ""))}</pre></div></details>')
            out.append('</div></details>')
    if skipped:
        out.append('<p class="muted" style="font-size:.88rem">' + t("Без улучшенной версии: ", "No improved version: ") + ", ".join(
            f'{e(u)} ({e(p.get("skipped", "—"))})' for u, p in skipped) + '</p>')
    return "\n".join(out)


def strength_cls(S: float) -> str:
    return "ok" if S >= 0.75 else "bad" if S < 0.45 else "warn" if S < 0.55 else ""


def pbar(P, lo, hi) -> str:
    return (f'<span class="barbox"><span class="iv" style="left:{lo*100:.0f}%;width:{max(1,(hi-lo)*100):.0f}%"></span>'
            f'<span class="pt" style="left:{P*100:.0f}%"></span></span>')


SIDE = {"for": ("за", "for"), "against": ("против", "against")}
DISC = {"eliminated": ("отсекает", "rules it out"), "weakened": ("ослабляет", "weakens it"), "unchanged": ("не различает", "does not tell apart")}


def dn(d: str) -> tuple[str, str]:
    return DESIGN_NAMES.get(d or "none", (d or "—", d or "—"))


def link_table(h: str, x: dict) -> str:
    """The table of links of one hypothesis: F / A, S with its interval, R, the link's novelty level, the records (weight;
    the quote on hovering a PMID)."""
    from hyparena.card import rules_v32 as r32_
    lv = x.get("link_levels") or {}
    rows = []
    for c in x["chain"]:
        R = r32_.non_refutation(c["F"], c["A"])
        recs = "".join(
            f'<a class="rec {"ok" if r["side"] == "for" else "bad"} tip" data-ru="{e(tn_ru(SIDE[r["side"]]) + " · " + dn(r["design"])[0] + (" · n " + str(r["n"]) if r["n"] else "") + " · вес " + fmt(r["w"], 3) + " — «" + (r["quote"] or "")[:420] + "»")}" '
            f'data-en="{e(SIDE[r["side"]][1] + " · " + dn(r["design"])[1] + (" · n " + str(r["n"]) if r["n"] else "") + " · weight " + fmt(r["w"], 3) + " — “" + (r["quote"] or "")[:420] + "”")}" '
            f'href="https://pubmed.ncbi.nlm.nih.gov/{e(r["pmid"])}/" target="_blank" rel="noopener">{e(r["pmid"])} <span class="mono">{fmt(r["w"], 2)}</span></a>'
            for r in c["records"][:14]) + (f' <span class="muted">+{len(c["records"]) - 14}</span>' if len(c["records"]) > 14 else "")
        rows.append(f'<tr id="b-{e(h)}-{e(c["id"])}"><td><span class="eyebrow">{tn(LINK_NAMES.get(c["link"], (c["link"],) * 2))}</span><br>{e(c["text"])}'
                    + (f'<br><span class="muted" style="font-size:.78rem">{t("признак старения","hallmark")}: {e(c["hallmark"])}</span>' if c["hallmark"] else "") + '</td>'
                    f'<td class="n">{fmt(c["F"], 3)} / {fmt(c["A"], 3)}</td>'
                    f'<td class="n"><span class="{strength_cls(c["S"])} pad">{fmt(c["S"])}</span><br><span class="muted" style="font-size:.75rem">[{fmt(c["lo"])}; {fmt(c["hi"])}]</span></td>'
                    f'<td class="n"{" style=\"color:var(--bad);font-weight:600\"" if R < 0.999 else ""}>{fmt(R)}</td>'
                    f'<td><span class="chip">{tn(NOVELTY_NAMES.get(lv.get(c["id"]), NOVELTY_NAMES[None]))}</span></td>'
                    f'<td class="recs">{recs or "<span class=muted>" + t("записей нет","no records") + "</span>"}</td></tr>')
    alts = ""
    if x.get("alternatives"):
        alts = ('<p style="margin:.8em 0 .2em"><b>' + tip("alt", t("Альтернативные объяснения", "Alternative explanations")) + '</b></p><ul>' + "".join(
            f'<li>{e(a["text"])} — {t("поддержка","support")} <span class="mono">{fmt(a["support"])}</span>; '
            f'{t("эксперимент: при успехе","experiment: if positive")} {tn(DISC.get(a["on_positive"], (a["on_positive"],) * 2))}, {t("при неудаче","if negative")} {tn(DISC.get(a["on_negative"], (a["on_negative"],) * 2))}'
            f'<br><span class="muted" style="font-size:.85rem">{e(a["why"] or "")}</span></li>' for a in x["alternatives"]) + '</ul>')
    exp = x.get("experiment") or {}
    return ('<div class="scroll" style="margin-top:10px"><table class="tbl links"><thead><tr>'
            f'<th>{tip("link", t("Звено","Link"))}</th><th>{tip("FA","F / A")}</th><th>{tip("S","S [90%]")}</th><th>{tip("R","R")}</th>'
            f'<th>{tip("link_N", t("Новизна звена","Link novelty"))}</th><th>{tip("records", t("Записи PubMed (PMID, вес)","PubMed records (PMID, weight)"))}</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>' +
            f'<p class="muted" style="font-size:.85rem">{t("Заявленный эксперимент: ","Stated experiment: ")}{e(exp.get("design") or "—")}, '
            f'{e(exp.get("endpoint") or "—")}; n {e(exp.get("n") or "—")}</p>' + alts)


def tn_ru(pair) -> str:
    return pair[0]


def render_sources(H: dict) -> str:
    """Every record of the pool, one row per paper and link: PMID, hypothesis, link, for or against, design, n, weight, quote."""
    rows = []
    for h, x in H.items():
        for c in x.get("chain") or []:
            for r in c["records"]:
                rows.append((r["pmid"], h, x, c, r))
    rows.sort(key=lambda z: (z[0], z[1]))
    out = [f'<h2>{t("Источники: все записи пула","Sources: every record of the pool")}</h2><p class="muted">' + t(
        f"Записей: {len(rows)}, статей: {len({z[0] for z in rows})}. Только статьи до даты среза; цитата — дословно из аннотации. Вес — произведение множителей дизайна, точности, эффекта, сравнения и контекста (справка).",
        f"Records: {len(rows)}, papers: {len({z[0] for z in rows})}. Papers before the cut-off only; the quote is verbatim from the abstract. The weight is the product of design, precision, effect, comparison and context (help).") + '</p>',
           '<div class="tools"><input id="sq" type="search" placeholder="PMID / NCT / текст" oninput="srcFilter()"></div>',
           '<div class="scroll"><table class="tbl sortable" id="srct"><thead><tr><th>PMID</th><th>' + t("Гипотеза","Hypothesis") + '</th><th>' +
           t("Звено","Link") + '</th><th>' + tip("side", t("За / против","For / against")) + '</th><th>' + tip("design", t("Дизайн","Design")) +
           '</th><th>n</th><th>' + tip("w", t("Вес","Weight")) + '</th><th>' + t("Цитата","Quote") + '</th></tr></thead><tbody>']
    for pmid, h, x, c, r in rows:
        q = e(f'{pmid} {h} {r["quote"] or ""}'.lower())
        out.append(f'<tr data-q="{q}"><td><a href="https://pubmed.ncbi.nlm.nih.gov/{e(pmid)}/" target="_blank" rel="noopener">{e(pmid)}</a></td>'
                   f'<td><a href="#h-{e(h)}">{e(h)}</a></td><td>{tn(LINK_NAMES.get(c["link"], (c["link"],) * 2))}</td>'
                   f'<td><span class="chip {"ok" if r["side"] == "for" else "bad"}">{tn(SIDE[r["side"]])}</span></td><td>{tn(dn(r["design"]))}</td>'
                   f'<td class="n">{e(r["n"] or "—")}</td><td class="n" data-v="{r["w"]}">{fmt(r["w"], 3)}</td>'
                   f'<td><blockquote>{e((r["quote"] or "")[:300])}</blockquote></td></tr>')
    out.append('</tbody></table></div>')
    return "\n".join(out)


GLOSSARY_EXTRA = {
    "FA": ("Веса F / A: суммарный вес записей «за» (F) и «против» (A) звена. Вес записи = дизайн × точность × эффект × сравнение × контекст (v3.6, по доменам GRADE); одна большая РКИ или метаанализ в точной популяции со средним или крупным эффектом весит 1. Несколько записей одной статьи или одного испытания: самая весомая целиком, остальные по 1/4.",
           "Weights F / A: the summed weight of the records for (F) and against (A) a link. A record's weight = design × precision × effect × comparison × context; one large RCT in the exact population with a large effect weighs 1. Several records of one paper or trial: the heaviest fully, the rest at 1/4."),
    "R": ("Неопровергнутость звена R = (1 + cF) / (1 + cF + cA), c = 6.67: 1, если данных «против» нет; данные «против» снижают её, данные «за» смягчают снижение. P гипотезы — произведение R по звеньям.",
          "Non-refutation of a link R = (1 + cF) / (1 + cF + cA), c = 6.67: 1 when nothing is against; data against lower it, data for soften that. P of the hypothesis is the product of R over the links."),
    "link_N": ("Новизна звена: ступень по ближайшей записи этого звена — новый контекст (то же вмешательство на том же виде), перенос (только на другом виде), аналог (только родственное вмешательство), новое звено (записей нет).",
               "Link novelty: the level of the closest record of this link: new context (the same intervention in the same species), translation (only another species), analog (only a related intervention), new link (no records)."),
    "records": ("Записи PubMed по звену: PMID и вес. Зелёные — «за», красные — «против». Наведите на запись, чтобы увидеть дизайн, n и дословную цитату; клик открывает статью.",
                "PubMed records of the link: PMID and weight. Green: for, red: against. Hover for the design, n and the verbatim quote; a click opens the paper."),
    "link": ("Звено механизма: доставка, действие на мишень, сигнальный путь, промежуточный эффект, исход. Цепочка звеньев ведёт от вмешательства к исходу.",
             "A link of the mechanism: delivery, target engagement, pathway, intermediate effect, outcome. The chain leads from the intervention to the outcome."),
    "alt": ("Альтернативное объяснение того же результата. Учитывается в I, только если у него есть поддержка в литературе и заявленный эксперимент его отсекает или ослабляет.",
            "An alternative explanation of the same result. It counts in I only with support in the literature and when the stated experiment rules it out or weakens it."),
    "side": ("«За» — находка подтверждает звено; «против» — результат нулевой или противоположный для этого же показателя. Значимый, но клинически малый эффект — «за» с малым весом, не «против».",
             "For: the finding supports the link; against: a null or opposite result for the same measure. A significant but clinically small effect is for with a small weight, not against."),
    "design": ("Дизайн исследования из аннотации: клетки, животные, наблюдательное, обзор, нерандомизированное, метаанализ, РКИ. Для звена исхода о людях — шкала 1/7 … 7/7; для звеньев до исхода — клетки 1/3, обзор 2/3, первичное исследование 1.",
               "Design from the abstract: cells, animals, observational, review, non-randomised, meta-analysis, RCT. For an outcome link about humans the scale is 1/7 … 7/7; before the outcome: cells 1/3, review 2/3, primary study 1."),
    "w": ("Вес записи (v3.6) — произведение множителей: дизайн (РКИ и метаанализ 1, нерандомизированное и наблюдательное 1/2, прочее 1/4), точность (по n; нулевой результат — по мощности; до исхода 1/2), эффект (средний или крупный 1, иначе 1/2), сравнение (между группами 1, иначе 1/2), контекст (соседний 1/2, иначе 1).",
          "Record weight: the product of design, precision (from n; 1/2 before the outcome), effect, comparison (between groups 1, before/after 2/3, none 1/3) and context (exact 1, adjacent 2/3, related intervention 1/3)."),
    "tuned": ("Доработанная версия: к гипотезе применены только исправимые пункты её разбора; новые части родителя сохранены (версия, сдвинутая к известному, возвращается писателю).",
              "Tuned version: only the fixable items of the analysis were applied; the parent's new parts are kept (a version that moved towards the known goes back to the writer)."),
    "free": ("Свободная эволюция: писатель мог изменить всё под выбранный профиль; названные им статьи засчитаны, только если их нашёл проверяющий до даты среза.",
             "Free evolution: the writer could change anything for the chosen profile; the papers it named count only if the verifier found them before the cut-off."),
    "drift": ("Сдвиг к известному: у улучшенной версии новизна ниже, чем у родителя, или сохранённое звено стало ближе к уже показанному, или пропало новое звено. Версия остаётся в рейтинге, флаг лишь предупреждает.",
              "Moved towards the known: the improved version is less novel than the parent, a kept link moved closer to what is shown, or the new link disappeared. The version stays in the ranking; the flag only warns."),
    "flags": ("Флаги — подсказки для улучшения: механизм не выписан, нет подкреплённых альтернатив, эксперимент оставляет альтернативы, спорное звено и др.",
              "Flags: hints for improving: no mechanism, no supported alternatives, the experiment leaves alternatives standing, a contested link and others."),
}


def t_ru(pair) -> str:
    return pair[0]


GLOSSARY_NAMES = {"score": ("ожидаемая оценка", "expected score"), "top5": ("вероятность топ-5", "probability of top 5"),
                  "place": ("место", "place"), "room": ("запас улучшения", "room to improve"), "S": ("сила звена S", "link strength S"),
                  "FA": ("веса F / A", "weights F / A"), "R": ("неопровергнутость звена R", "link non-refutation R"),
                  "link_N": ("новизна звена", "link novelty"), "records": ("записи PubMed", "PubMed records"), "link": ("звено", "link"),
                  "alt": ("альтернатива", "alternative"), "side": ("за / против", "for / against"), "design": ("дизайн", "design"),
                  "w": ("вес записи", "record weight"), "flags": ("флаги", "flags"), "tuned": ("доработанная версия", "tuned version"),
                  "free": ("свободная эволюция", "free evolution"), "drift": ("сдвиг к известному", "moved towards the known")}


def glossary_items() -> list[tuple[str, tuple[str, str]]]:
    names = {**IND_NAMES, **GLOSSARY_NAMES}
    return [(names.get(k, (k, k))[0], v) for k, v in {**TIPS, **GLOSSARY_EXTRA}.items()]


def glossary() -> str:
    """Every parameter of the report with its note (the same texts as the hover notes)."""
    items = {**TIPS, **GLOSSARY_EXTRA}
    names = {**{k: v for k, v in IND_NAMES.items()}, "score": ("ожидаемая оценка", "expected score"), "top5": ("вероятность топ-5", "probability of top 5"),
             "place": ("место", "place"), "room": ("запас улучшения", "room to improve"), "S": ("сила звена S", "link strength S"),
             "FA": ("веса F / A", "weights F / A"), "R": ("неопровергнутость звена R", "link non-refutation R"), "link_N": ("новизна звена", "link novelty"),
             "records": ("записи PubMed", "PubMed records"), "link": ("звено", "link"), "alt": ("альтернатива", "alternative"),
             "side": ("за / против", "for / against"), "design": ("дизайн", "design"), "w": ("вес записи", "record weight"), "flags": ("флаги", "flags")}
    return ('<div class="card"><h3>' + t("Глоссарий: все параметры отчёта", "Glossary: every parameter of the report") + '</h3><dl class="gl">' + "".join(
        f'<dt>{tn(names.get(k, (k, k)))}</dt><dd>{t(e(v[0]), e(v[1]))}</dd>' for k, v in items.items()) + '</dl></div>')


def render(rep: dict) -> str:
    m, H = rep["meta"], rep["hyps"]
    head_out = out = ['<!doctype html><html lang="ru" data-lang="ru"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f'<title>Отчёт по пулу — {e(m["pool"])}</title>',
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Literata:opsz,wght@7..72,400;7..72,600&family=Onest:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">',
           f'<style>{CSS}</style></head><body>']
    views: dict[str, list[str]] = {}
    VIEWS = [("rank", t("Рейтинг", "Ranking")), ("hyp", t("Гипотезы", "Hypotheses"))] + \
        ([("evo", t("Эволюция", "Evolution"))] if rep.get("evolution") else []) + \
        [("src", t("Источники", "Sources")), ("help", t("Справка", "Help"))]
    out.append('<header class="band"><div class="wrap"><div class="bar1"><span class="badge">' + t("Метод v3.4 · АСПИД", "Method v3.4 · ASPID") +
               f'</span><span class="meta">{t("Дата среза","Cut-off date")} T = {e(m["date"])} · {t("оценено","scored")} {m["n_scored"]} / {m["n"]}</span>'
               '<span class="sp"></span><button class="sw" onclick="setLang(\'ru\')">RU</button><button class="sw" onclick="setLang(\'en\')">EN</button>'
               '<button class="sw" onclick="setTheme()">◐</button></div>'
               f'<h1>{t(e(m["title_ru"]), e(m["title_en"]))}</h1><nav class="vtabs">' +
               "".join(f'<button data-view="{k}" onclick="showView(\'{k}\')">{lab}</button>' for k, lab in VIEWS) +
               '</nav></div></header><main class="wrap">')
    out = views.setdefault("rank", [])
    out.append(f'<p class="prose muted" style="margin-top:18px">{t(e(m["about_ru"]), e(m["about_en"]))} ' +
               t('Как читать показатели — во вкладке <a href="#help" onclick="showView(\'help\')">«Справка»</a>; у каждого подчёркнутого термина есть подсказка при наведении.',
                 'How to read the indicators: the <a href="#help" onclick="showView(\'help\')">Help</a> tab; every underlined term has a hover note.') + '</p>')
    if rep.get("evolution"):
        n_ev = sum(1 for p in rep["evolution"].values() if p.get("compare"))
        out.append('<p><a class="pill" href="#evo" onclick="showView(\'evo\')">' + t(
            f"Улучшенных версий в рейтинге: {n_ev} — сравнение «до → после» →", f"Improved versions in the ranking: {n_ev}: before → after →") + '</a></p>')
    out = views.setdefault("help", [])
    # 1. how to read
    out.append(f'<h2 id="read">{t("Как читать этот отчёт","How to read this report")}</h2><div class="prose">')
    out.append('<p>' + t(
        "<b>1. Механизм.</b> Гипотеза разбирается на цепочку звеньев от вмешательства до исхода («упражнения → мышечная сила → "
        "функция»). Для каждого звена ищутся статьи PubMed до даты оценки; каждая находка записывается с дословной цитатой и "
        "весом: надёжнее дизайн, больше выборка, крупнее эффект, ближе условия — больше вес.",
        "<b>1. Mechanism.</b> A hypothesis is split into a chain of links from the intervention to the outcome (\"exercise → "
        "muscle strength → function\"). For each link PubMed is searched up to the date of scoring; every finding is recorded "
        "with a verbatim quote and a weight: a more reliable design, a larger sample, a larger effect and closer conditions "
        "weigh more.") + '</p>')
    out.append('<p>' + t(
        f"<b>2. Показатели.</b> Из записей код считает {tip('P','P — неопровергнутость механизма')}, {tip('I','I — информативность эксперимента')}, "
        f"{tip('W','размах')} и ещё несколько показателей. Наведите на подчёркнутый термин, чтобы увидеть пояснение. Исход испытания "
        "метод <b>не предсказывает</b>: он оценивает, насколько обоснован механизм сейчас и что даст эксперимент.",
        f"<b>2. Indicators.</b> From the records the code computes {tip('P','P, non-refutation of the mechanism')}, "
        f"{tip('I','I, informativeness of the experiment')}, {tip('W','scope')} and a few more. Hover over an underlined term "
        "for its meaning. The method does <b>not</b> predict the trial's result: it measures how well the mechanism is "
        "supported now and what the experiment would teach.") + '</p>')
    out.append('<p>' + t(
        "<b>3. Рейтинг — АСПИД.</b> Одного «правильного» веса у показателей нет: инвестору важнее одно, исследователю — другое. "
        "Поэтому задаётся только <b>профиль</b> — порядок важности (например, «неопровергнутость важнее информативности, та — важнее "
        "размаха»), а точные веса разыгрываются:",
        "<b>3. Ranking: ASPID.</b> There is no single right weighting of the indicators: an investor cares about one thing, a "
        "researcher about another. So only a <b>profile</b> is set, an order of importance (e.g. \"non-refutation above "
        "informativeness, informativeness above scope\"), and the exact weights are drawn:") + '</p></div>')
    out.append('<div class="steps">' + '<span class="arrow">→</span>'.join(f'<span class="st">{x}</span>' for x in [
        t("порядок важности профиля", "the profile's order of importance"),
        t("10 000 случайных наборов весов, совместимых с порядком", "10,000 random weight sets compatible with the order"),
        t("оценка каждой гипотезы в каждом наборе", "a score for each hypothesis in each set"),
        t(f"{tip('score','ожидаемая оценка')} → {tip('place','место')}; {tip('top5','вероятность топ-5')}",
          f"{tip('score','expected score')} → {tip('place','place')}; {tip('top5','probability of top 5')}")]) + '</div>')
    out.append('<p class="prose">' + t(
        "Очень низкая неопровергнутость не компенсируется другими показателями. Вероятность топ-5 показывает, насколько место "
        "устойчиво: 0.9 — гипотеза в пятёрке почти при любых весах, 0.2 — только при некоторых.",
        "A very low non-refutation is not compensated by the other indicators. The probability of top 5 shows how robust the place "
        "is: 0.9 means in the top 5 under almost any weights, 0.2 only under some.") + '</p>')
    # 2. ranking table per profile
    out = views["rank"]
    profs = list(m["profiles"])
    out.append(f'<h2 id="table">{t("Рейтинг по профилям","Ranking by profile")}</h2>')
    out.append('<div class="tabs" role="tablist">' + "".join(
        f'<button data-p="{p}" aria-selected="{"true" if i == 0 else "false"}" onclick="showProfile(\'{p}\')">{tn(PROFILE_NAMES[p])}</button>'
        for i, p in enumerate(profs)) + '</div>')
    types = sorted({x.get("type") for x in H.values() if x.get("type")})
    out.append('<div class="tools"><input id="fq" type="search" placeholder="поиск / search">'
               '<select id="ftype"><option value="">все типы / all types</option>' +
               "".join(f'<option value="{e(ty)}">{e(" / ".join(TYPE_NAMES.get(ty, (ty, ty))))}</option>' for ty in types) +
               '</select><span class="muted">' + t("клик по заголовку сортирует", "click a header to sort") + '</span></div>')

    def room_cell(x, p):
        r = x.get("room") or {}
        a, b = (r.get("score") or {}).get(p, [None, None])
        if a is None or b is None:
            return '<td class="n" data-v="-9">—</td>'
        g = b - a
        n0, n1 = r.get("N", [None, None])
        down = n0 in ORDINAL["N"] and n1 in ORDINAL["N"] and ORDINAL["N"].index(n1) < ORDINAL["N"].index(n0)
        mark = ("*" if r.get("not_computed") else "") + (' <span class="down">↓</span>' if down else "")
        return f'<td class="n" data-v="{g:.4f}">{"+" if g > 0.0005 else ""}{fmt(g, 3)}{mark}</td>'

    def cell(ind, x):
        v = x["values"].get(ind)
        if ind == "P":
            iv = (f'<br><span class="muted" style="font-size:.78rem">{fmt(x["P_lo"])}–{fmt(x["P_hi"])}</span>' if x["P_lo"] != x["P_hi"] else "")
            red = ' style="color:var(--bad);font-weight:600"' if x["P"] < 0.999 else ""
            return f'<td class="n" data-c="P" data-v="{x["P"]}"><span{red}>{fmt(x["P"])}</span>{iv}</td>'
        if ind == "N":
            lv = ORDINAL["N"]
            src = (f'<br><a class="mono" style="font-size:.75rem" href="https://pubmed.ncbi.nlm.nih.gov/{e(x["N_pmid"])}/" target="_blank" rel="noopener">PMID {e(x["N_pmid"])}</a>' if x.get("N_pmid") else "")
            return f'<td data-c="N" data-v="{lv.index(v) if v in lv else -1}"><span class="chip">' + tip("N", tn(NOVELTY_NAMES.get(v, NOVELTY_NAMES[None]))) + f'</span>{src}</td>'
        if ind == "I":
            hd = x["values"].get("I_headroom")
            return (f'<td class="n" data-c="I" data-v="{x["I"]}">{fmt(x["I"])}' +
                    (f'<br><span class="muted" style="font-size:.75rem">{t("запас","room")} {fmt(hd)}</span>' if hd and hd > x["I"] + 0.005 else "") + '</td>')
        if ind == "W":
            return f'<td data-c="W" data-v="{ORDINAL["W"].index(v) if v in ORDINAL["W"] else -1}">{tn(SCOPE_NAMES.get(v, (str(v),)*2))}</td>'
        if ind == "endpoint_clinical":
            return f'<td data-c="{ind}" data-v="{ORDINAL[ind].index(v) if v in ORDINAL[ind] else -1}">{tn(ENDPOINT_NAMES.get(v, ("—","—")))}</td>'
        if ind == "ai_role":
            return f'<td data-c="{ind}" data-v="{ORDINAL[ind].index(v) if v in ORDINAL[ind] else -1}">{tn(AI_NAMES.get(v or "none"))}</td>'
        if ind == "best_design_outcome":
            lv = ORDINAL[ind]
            return f'<td data-c="{ind}" data-v="{lv.index(v) if v in lv else -1}">{tn(DESIGN_NAMES.get(v or "none", (str(v),) * 2))}</td>'
        if v is None:
            return f'<td class="n" data-c="{ind}" data-v="-9">—</td>'
        if ind == "independent_outcome":
            return f'<td class="n" data-c="{ind}" data-v="{v}">{int(v)}</td>'
        if ind == "against_share":
            return f'<td class="n" data-c="{ind}" data-v="{v}">{round(v * 100)}%</td>'
        return f'<td class="n" data-c="{ind}" data-v="{v}">{fmt(v)}</td>'

    for i, p in enumerate(profs):
        inds = [ind for tier in m["profiles"][p] for ind in tier]
        out.append(f'<div class="ptab" data-p="{p}"{"" if i == 0 else " hidden"}>')
        out.append('<p class="muted" style="font-size:.9rem">' + t("Порядок важности: ", "Order of importance: ") + " &gt; ".join(
            "{" + ", ".join(tn(IND_NAMES.get(ind, (ind, ind))) for ind in tier) + "}" if len(tier) > 1 else tn(IND_NAMES.get(tier[0], (tier[0],) * 2))
            for tier in m["profiles"][p]) + '</p>')
        out.append('<div class="cols">' + t("Показатели в таблице: ", "Indicators shown: ") + "".join(
            f'<label><input type="checkbox" data-c="{ind}" {"checked" if k < 4 else ""} onchange="cols(this)"> {tn(SHORT.get(ind, (ind, ind)))}</label>'
            for k, ind in enumerate(inds)) + '</div>')
        out.append('<div class="scroll"><table class="tbl sortable"><thead><tr>' +
                   f'<th>{tip("place","#")}</th><th>{t("Гипотеза","Hypothesis")}</th><th>{tip("score",t("Оценка","Score"))}</th>'
                   f'<th>{tip("top5",t("Топ-5","Top 5"))}</th><th>{tip("room",t("Запас","Room"))}</th>' +
                   "".join(f'<th data-c="{ind}">{tip(ind, tn(SHORT.get(ind, (ind, ind))))}</th>' for ind in inds) + '</tr></thead><tbody>')
        for h in rep["ranks"][p]:
            x = H[h]
            rk = x["rank"][p]
            lead = False                       # no separate top 3 (user decision 2026-11-07)
            why = ""
            if lead:
                ups = x["contrib"][p]["up"]
                why = '<br><span class="star">★ </span><span class="muted" style="font-size:.82rem">' + t("сильные стороны: ", "strengths: ") + \
                      (", ".join(tn(IND_NAMES.get(ind, (ind, ind))) for ind, _ in ups) or "—") + '</span>'
            q = e((x["title"] + " " + h).lower())
            out.append(f'<tr class="{"lead" if lead else ""}" data-type="{e(x.get("type"))}" data-q="{q}"><td class="n" data-v="{rk}">{rk}</td>'
                       f'<td class="title">' + evo_chip(x) +
                       f'<a href="#h-{e(h)}">{e(x["title"][:90])}</a><br><span class="muted mono">{e(h)}</span> · '
                       f'<span class="muted">{tn(TYPE_NAMES.get(x.get("type"), ("—","—")))}</span>{why}</td>'
                       f'<td class="n" data-v="{x["aspid"][p]}">{fmt(x["aspid"][p], 3)}</td><td class="n" data-v="{x["p_top5"][p]}">{fmt(x["p_top5"][p])}</td>' +
                       room_cell(x, p) +
                       "".join(cell(ind, x) for ind in inds) + '</tr>')
        out.append('</tbody></table></div><div class="pager"><button onclick="page(this,-1)">‹</button><span class="pinfo"></span>'
                   '<button onclick="page(this,1)">›</button></div></div>')
    unscored = [h for h in H if H[h].get("P") is None or H[h].get("gate") != "pass"]
    if unscored:
        out.append('<p class="muted" style="font-size:.88rem">' + t("Не вошли в рейтинг: ", "Not ranked: ") + ", ".join(
            f'<a href="#h-{e(h)}">{e(h)}</a> ({e(H[h]["outcome"]) if H[h].get("P") is None else t("отсечена правилом опровержения","filtered by the gate")})'
            for h in unscored) + '</p>')
    first = profs[0]
    order = rep["ranks"][first] + [h for h in H if h not in rep["ranks"][first]]   # the first profile's order, then the unranked
    # 4. each hypothesis
    out = views.setdefault("hyp", [])
    out.append(f'<h2 id="each">{t("Гипотезы: звенья, записи, что улучшить","Hypotheses: links, records, what to improve")}</h2><p class="muted">' + t(
        "Раскройте строку. В карточке: цепочка звеньев, таблица звеньев (веса F / A, сила S, неопровергнутость R, новизна звена, записи с весом; цитата — при наведении на PMID), альтернативы, что поднимет оценку.",
        "Open a row. Inside: the chain, the table of links (weights F / A, strength S, non-refutation R, link novelty, records with weights; the quote on hovering a PMID), the alternatives, what would raise the score.") +
        f' <button class="sw" onclick="openAll(true)">{t("развернуть все","open all")}</button> <button class="sw" onclick="openAll(false)">{t("свернуть все","close all")}</button></p>')
    for h in order:
        x = H[h]
        if x.get("P") is None:
            out.append(f'<details id="h-{e(h)}"><summary><b>{e(x["title"][:110])}</b> <span class="muted mono">{e(h)}</span> — '
                       f'{t("не оценена","not scored")} ({e(x["outcome"])})</summary><div class="body"><p class="muted">' + t(
                           "Гипотеза не прошла вход или была отсечена правилом опровержения; подробности — в данных прогона.",
                           "The hypothesis did not pass the entry or was filtered by the refutation rule; details are in the run data.") + '</p></div></details>')
            continue
        w = next((c for c in x["chain"] if c["id"] == x["weakest"]), None)
        s = next((c for c in x["chain"] if c["id"] == x["strongest"]), None)
        P = fmt(x['P'])
        unchecked = [c for c in x["chain"] if c["id"] in x.get("unchecked", [])]
        if len(x["chain"]) <= 1:
            verdict = t(f"P {P}; механизм не выписан — в цепочке только исход", f"P {P}; no mechanism written: the chain is the outcome only")
        elif w and w["S"] < 0.75:
            ln = LINK_NAMES.get(w["link"], (w["link"],) * 2)
            verdict = t(f"P {P}; слабое место — звено «{e(ln[0])}» (S {fmt(w['S'])})", f"P {P}; weakest link: {e(ln[1])} (S {fmt(w['S'])})")
        else:
            verdict = t(f"P {P}; данных против механизма нет", f"P {P}; no data against the mechanism")
        if unchecked and len(x["chain"]) > 1:
            verdict += t(f"; не проверено звеньев: {len(unchecked)} из {len(x['chain'])}", f"; unchecked links: {len(unchecked)} of {len(x['chain'])}")
        out.append(f'<details id="h-{e(h)}"><summary><b>{e(x["title"][:110])}</b> <span class="muted mono">{e(h)}</span><br>'
                   f'<span class="muted">{verdict}</span></summary><div class="body">')
        out.append(f'<p class="prose">{e(x["plain"])}</p>')
        def box(c):
            note = "" if c.get("checked", True) else f'<br><span class="chip">{t("нет данных — в P не входит","no data, not in P")}</span>'
            if c.get("parallel_outcome"):
                note = (f'<br><span class="chip ok">{t("основной исход","primary outcome")}</span>' if c["primary"] else
                        (f'<br><span class="chip">{t("в P не входит","not in P")}</span>' if not c["in_P"] else
                         f'<br><span class="chip">{t("в P — среднее исходов","in P: mean of outcomes")}</span>'))
            return (f'<a class="link {strength_cls(c["S"])}" href="#b-{e(h)}-{e(c["id"])}" style="text-decoration:none;color:inherit">'
                    f'<span class="eyebrow">{tn(LINK_NAMES.get(c["link"], (c["link"],)*2))}</span><br>{e(c["text"][:90])}<br>'
                    f'<span class="s">S {fmt(c["S"])} [{fmt(c["lo"])}; {fmt(c["hi"])}]</span> · {len(c["records"])} {t("зап.","rec.")}{note}</a>')
        mech = [c for c in x["chain"] if not c.get("parallel_outcome") and c["link"] != "outcome"]
        outs_ = [c for c in x["chain"] if c["link"] == "outcome"]
        parts = [box(c) for c in mech]
        if outs_:
            parts.append('<span style="display:flex;flex-direction:column;gap:6px">' + "".join(box(c) for c in outs_) + '</span>')
        out.append('<div class="chain">' + '<span class="arrow">→</span>'.join(parts) + '</div>')
        if len(outs_) > 1:
            out.append(f'<p class="muted" style="font-size:.85rem">{t("Параллельные исходы (масса, сила, функция) — одно звено: в P входит основной исход заявленного эксперимента, а если его нельзя выделить — среднее.","Parallel outcomes (mass, strength, function) are one link: P takes the primary outcome of the stated experiment, or their mean when none can be singled out.")}</p>')
        rows = [("P", f'<span class="mono">{fmt(x["P"])}' + (f' [{fmt(x["P_lo"])}; {fmt(x["P_hi"])}]' if x["P_lo"] != x["P_hi"] else "") + '</span>'),
                (t("Новизна","Novelty"), tn(NOVELTY_NAMES.get(x.get("N"), NOVELTY_NAMES[None]))),
                ("I", f'<span class="mono">{fmt(x["I"])}</span>'), (t("Подтверждённость","Supported"), f'<span class="mono">{fmt(x.get("support_share"))}</span>'), (t("Размах","Scope"), tn(SCOPE_NAMES.get(x["scope"], (x["scope"],)*2))),
                (t("Конечная точка","Endpoint"), tn(ENDPOINT_NAMES.get(x.get("endpoint_clinical"), ("—","—")))),
                (t("Роль ИИ","AI role"), tn(AI_NAMES.get(x.get("ai_role") or "none"))),
                (t("Места","Places"), " · ".join(f'{tn(PROFILE_NAMES[p])} {x["rank"].get(p, "—")}/{len(rep["ranks"][p])} ({t("топ-5","top 5")} {fmt(x["p_top5"].get(p))})' for p in profs))]
        out.append('<table class="tbl" style="max-width:760px">' + "".join(f'<tr><th style="position:static">{a}</th><td>{b}</td></tr>' for a, b in rows) + '</table>')
        rl = next((c for c in x["chain"] if c["id"] == x.get("raise_link")), None)
        up = sorted({i for p in profs for i, _ in x["contrib"][p]["up"]})
        down = sorted({i for p in profs for i, _ in x["contrib"][p]["down"]})
        pct = x["pct"]
        def pc(i):
            return f' <span class="muted">({t("лучше, чем у","better than")} {round((pct[i] or 0)*100)}% {t("пула","of the pool")})</span>'
        out.append('<div class="grid" style="margin-top:10px"><div class="card"><b class="up">▲ ' + t("Вытягивает","Lifts") + '</b><ul>' +
                   ("".join(f'<li>{tn(IND_NAMES.get(i, (i, i)))}{pc(i)}</li>' for i in up) or '<li class="muted">—</li>') +
                   (f'<li>{t("самое сильное звено: ","strongest link: ")}{tn(LINK_NAMES.get(s["link"], (s["link"],)*2))} (S {fmt(s["S"])})</li>' if s and s["S"] > 0.55 else "") +
                   '</ul></div><div class="card"><b class="down">▼ ' + t("Занижает","Lowers") + '</b><ul>' +
                   ("".join(f'<li>{tn(IND_NAMES.get(i, (i, i)))}{pc(i)}</li>' for i in down) or '<li class="muted">—</li>') +
                   (f'<li>{t("слабое звено: ","weakest link: ")}{tn(LINK_NAMES.get(w["link"], (w["link"],)*2))} (S {fmt(w["S"])}' +
                    (t(", данных нет", ", no data") if not w["records"] else "") + ')</li>' if w and w["S"] < 0.75 else "") +
                   '</ul></div></div>')
        out.append(link_table(h, x))
        out.append(render_items(x.get("improvements") or [], profs, x.get("room")))
        out.append('</div></details>')
    if rep.get("evolution"):
        views["evo"] = [render_evolution(rep["evolution"], H, profs)]
    views["src"] = [render_sources(H)]
    out = views["help"]
    # 5. appendices
    out.append(f'<h2 id="app">{t("Метод, глоссарий, происхождение","Method, glossary, provenance")}</h2>')
    out.append(glossary())
    out.append('<details><summary><b>' + t("А. Метод кратко и глоссарий","A. The method in brief and a glossary") + '</b></summary><div class="body prose">' + t(
        "<p><b>Запись</b> — находка из одной статьи по одному звену: дословная цитата, дизайн (от клеточного опыта до РКИ), "
        "размер выборки, величина эффекта, сравнение (между группами, до/после), совпадение условий. Её вес — произведение "
        "этих факторов; одна большая РКИ с крупным эффектом весит 1.</p><p><b>Сила звена S</b> — среднее бета-распределения по "
        "весам «за» и «против»: 0.5 без данных, 0.83 при весе «за» 0.6, около 0.5 при равном весе «за» и «против» (но с узким "
        "интервалом). Несколько записей одной статьи или одного испытания считаются как один источник.</p><p><b>Правило "
        "опровержения</b> — единственный фильтр: звено опровергнуто, если против него есть РКИ или метаанализ в той же "
        "популяции и нет столь же сильных данных «за».</p><p><b>Альтернатива</b> — конкурирующее объяснение того же результата; "
        "учитывается, только если у неё есть поддержка в литературе.</p><p>Подробно: мануал метода "
        "<code>docs/method-v3-manual.md</code>.</p>",
        "<p><b>Record</b>: a finding of one paper on one link: verbatim quote, design (from a cell study to an RCT), sample "
        "size, effect size, comparison (between groups, before/after), match of conditions. Its weight is the product of these "
        "factors; one large RCT with a large effect weighs 1.</p><p><b>Link strength S</b>: the mean of a Beta distribution "
        "over the weights for and against: 0.5 without data, 0.83 with a weight of 0.6 for, about 0.5 when for and against "
        "balance (but with a narrow interval). Several records of one paper or one trial count as one source.</p><p><b>Gate</b>, "
        "the only filter: a link is refuted when an RCT or meta-analysis in the same population is against it and nothing as "
        "strong is for it.</p><p><b>Alternative</b>: a competing explanation of the same result; it counts only with support in "
        "the literature.</p><p>In full: the method manual <code>docs/method-v3-manual.md</code>.</p>") + '</div></details>')
    out.append('<details><summary><b>' + t("В. Происхождение и ограничения","C. Provenance and limitations") + '</b></summary><div class="body prose"><ul>' +
               "".join(f'<li>{li}</li>' for li in [
                   t(f"Дата оценки {e(m['date'])}; литература — до этой даты.", f"Scored on {e(m['date'])}; literature up to that date."),
                   t(f"Метод: {e(m['method'])}. Оценки зафиксированы, SHA-256 {e(m['sha'])}.", f"Method: {e(m['method'])}. Scores frozen, SHA-256 {e(m['sha'])}."),
                   t(f"Исходы прогона: {e(m['outcomes'])}.", f"Run outcomes: {e(m['outcomes'])}."),
                   t("Проверяющая модель находит около 60% относящихся к делу статей и почти не берёт лишних: поддержка от вмешательств "
                     "того же рода часто пропускается, поэтому P программ и поведенческих вмешательств занижен.",
                     "The verifier finds about 60% of the relevant papers and almost no irrelevant ones: support from interventions of "
                     "the same kind is often missed, so P of programmes and behavioural interventions is biased down."),
                   t("Только аннотации статей; альтернативы предлагает модель по найденной литературе.",
                     "Abstracts only; alternatives are proposed by a model from the literature found."),
                   t("Связь P с исходами испытаний пока не доказана: на прошлых выборках AUC 0.61–0.65 при широких интервалах; этот пул — "
                     "проспективная проверка.",
                     "The link between P and trial outcomes is not established: AUC 0.61-0.65 on past samples with wide intervals; this pool "
                     "is the prospective test."),
               ]) + '</ul></div></details>')
    body = ["".join(head_out)]
    for k, _ in VIEWS:
        body.append(f'<section class="view" data-view="{k}" id="v-{k}">' + "\n".join(views.get(k, [])) + '</section>')
    body.append(f'</main><div id="tt" role="tooltip"></div><script>{JS}</script></body></html>')
    return "\n".join(body)


EVO_SUFFIX = "+evo"
EVO_SUFFIXES = {"tune": "+evo", "free": "+free"}
EVO_FILES = {"tune": "evolution_{n}.json", "free": "evolution_free_{n}.json"}


def evo_chip(x: dict) -> str:
    """Tuning and free evolution are named apart (user decision 2026-11-07)."""
    if not x.get("parent"):
        return ""
    if x.get("evo_mode") == "free":
        c = '<span class="chip ok">' + tip("free", t("свободная эволюция","free evolution")) + '</span> '
        if x.get("new_after"):
            c += f'<span class="chip">{t("новая гипотеза после ","new hypothesis after ")}{e(x["parent"])}</span> '
        return c
    return '<span class="chip ok">' + tip("tuned", t("доработанная версия","tuned version")) + '</span> '




def prospective(n: int = 60) -> tuple[dict, str]:
    from scripts.ctgov_outcomes import KG
    d = KG / "hypothesis_sources" / "prospective"
    run = json.loads((d / f"run_{n}.json").read_text())
    sf = d / f"scores_{n}_v34.json"
    sb = (sf if sf.exists() else d / f"scores_{n}.json").read_bytes()
    texts = {json.loads(l)["id"]: json.loads(l)["text"] for l in open(d / f"texts_{n}.jsonl")}
    meta = {"pool": f"prospective-{n}", "date": "2026-11-06", "sha": hashlib.sha256(sb).hexdigest(),
            "method": "v3.6 (GRADE-shaped record weight, log-likelihood fold; evidence balance in the profiles, null by power; v3.4 novelty), normalize_card/v10, verify_claim/v9, ASPID: evidence trial-5, funding trial-6, frontier trial-2",
            "title_ru": f"Проспективный пул: {n} идущих испытаний", "title_en": f"Prospective pool: {n} ongoing trials",
            "about_ru": "Испытания на ClinicalTrials.gov, где среди состояний — само старение, с завершением в ноябре 2026 — декабре 2028; "
                        "по 15 на тип вмешательства. Оценены до появления результатов; оценки зафиксированы хешем.",
            "about_en": "ClinicalTrials.gov trials with ageing itself among the conditions, primary completion November 2026 – December 2028; "
                        "15 per intervention type. Scored before any result; the scores are frozen with a hash."}
    scores = json.loads(sb)
    units = json.loads((d / f"units_{n}.json").read_text())
    unit_by = {u["id"]: u for u in units}
    evos = {}
    for mode, fname in EVO_FILES.items():
        f = d / fname.format(n=n)
        if not f.exists():
            continue
        for u, p in json.loads(f.read_text())["pairs"].items():          # improved versions join the ranking as their own rows
            p.setdefault("mode", mode)
            evos[(mode, u)] = p
            cr = p.get("child_run") or {}
            child = (cr.get("items") or [{}])[0]
            if not child.get("card"):
                continue
            cid = u + EVO_SUFFIXES[mode]
            run = {**run, cid: {"items": [child], "meta": {**cr.get("meta", {}), "as_of": run[u]["meta"].get("as_of")}}}
            scores[cid] = {"endpoint_clinical": p.get("child_endpoint"), "trend_pubmed": scores.get(u, {}).get("trend_pubmed"),
                           "ai_role": child["card"].get("ai_role", "none"), "P": 0}
            units.append({**unit_by.get(u, {}), "id": cid, "evo_mode": mode, "new_after": p.get("new_hypothesis_after")})
            texts[cid] = p.get("child_text", "")
    rep = build(run, scores, units, texts, meta)
    if evos:
        from hyparena.card import evolve_v3
        out = {}
        for (mode, u), p in evos.items():
            child = (p.get("child_run") or {}).get("items", [{}])[0]
            if child and u in rep["hyps"] and "values" in rep["hyps"][u]:
                v = rep["hyps"][u]["values"]
                pe = {k: v.get(k) for k in ("feasibility", "best_design_outcome", "independent_outcome", "against_share",
                                            "endpoint_clinical", "trend_pubmed", "ai_role")}
                ce = {**pe, "endpoint_clinical": p.get("child_endpoint"), "ai_role": (child.get("card") or {}).get("ai_role", pe.get("ai_role"))}
                p["compare"] = evolve_v3.compare(run[u]["items"][0], child, pe, ce)
            out[u if mode == "tune" else u + EVO_SUFFIXES[mode]] = p
        rep["evolution"] = out
    return rep, str(d / f"report_{n}.html")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pool", choices=["prospective"])
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    rep, default = prospective(a.n)
    out = Path(a.out or default)
    out.write_text(render(rep), encoding="utf-8")
    print(out, round(out.stat().st_size / 1024), "KB")


if __name__ == "__main__":
    main()

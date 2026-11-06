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
                 "funding": ("Финансирование", "Funding")}
IND_NAMES = {
    "P": ("правдоподобие механизма", "plausibility of the mechanism"),
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
}
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
         "ai_role": ("ИИ", "AI"), "support_share": ("Подтв.", "Supported")}
DESIGN_NAMES = {"none": ("нет данных", "no data"), "cells": ("клетки", "cells"), "animal": ("животные", "animals"),
                "observational": ("наблюдательное", "observational"), "review": ("обзор", "review"),
                "non_randomised": ("нерандомиз.", "non-randomised"), "meta_analysis": ("метаанализ", "meta-analysis"), "rct": ("РКИ", "RCT")}
ORDINAL = {"W": ("local", "organ", "hallmark"), "endpoint_clinical": ("biomarker", "patient_reported", "function", "clinical_event"),
           "ai_role": ("none", "analysis", "in_the_loop", "intervention"),
           "best_design_outcome": aspid_v3.SPECS["best_design_outcome"].levels}


TIPS = {
    "P": ("Правдоподобие механизма, от 0 до 1: произведение силы звеньев цепочки. Звено без данных не учитывается (его отражает ось «подтверждённость»); данные «за» поднимают силу звена выше 0.5, «против» — опускают ниже. Под числом — 90%-й интервал: широкий, когда о звеньях мало известно.",
          "Plausibility of the mechanism, 0 to 1: the product of the links' strengths. A link without data does not count (the support axis carries it); data for raise a link above 0.5, against lower it. Below the number: the 90% interval, wide when little is known."),
    "I": ("Информативность эксперимента, от 1/3 до 1: сколько подкреплённых литературой альтернативных объяснений отсечёт заявленный эксперимент. 1/3 — ни одного.",
          "Informativeness, 1/3 to 1: how many literature-supported alternative explanations the stated experiment rules out. 1/3: none."),
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
    "support_share": ("Подтверждённость механизма, от 0 до 1: средняя подтверждённость звеньев цепочки. Звено без данных или с данными только «против» — 0, умеренная поддержка — 0.67, сильная — около 1. Звенья без данных не снижают P, но снижают эту ось: гипотеза из одних догадок не получит высокое место.",
                      "How much of the mechanism is supported, 0 to 1: the mean support of the chain's links. A link without data or with data only against is 0, moderate support 0.67, strong near 1. Links without data do not lower P but lower this axis: a hypothesis made of guesses does not rank high."),
    "ai_role": ("Роль ИИ в гипотезе: нет / анализ данных / ИИ в цикле эксперимента / ИИ — само вмешательство; ставится только по дословной фразе текста.",
                "Role of AI: none / data analysis / AI in the experiment loop / AI is the intervention; set only from a verbatim phrase of the text."),
    "score": ("Ожидаемая оценка в профиле, от 0 до 1: среднее по 10 000 случайным наборам весов, совместимым с порядком важности профиля.",
              "Expected score under the profile, 0 to 1: the mean over 10,000 random weight sets compatible with the profile's order of importance."),
    "top5": ("Вероятность попасть в первую пятёрку пула по этому профилю: доля из 10 000 розыгрышей весов, где гипотеза оказалась в пятёрке. Показывает, насколько место устойчиво к выбору весов.",
             "Probability of being in the pool's top 5 under this profile: the share of 10,000 weight draws in which the hypothesis was in the top 5; how robust the place is to the choice of weights."),
    "place": ("Место по ожидаемой оценке (1 — лучшая).", "Place by the expected score (1 = best)."),
    "S": ("Сила звена, от 0 до 1: 0.5 — данных нет; 0.83 — умеренная поддержка; около 0.5 с узким интервалом — данные «за» и «против» уравновешены.",
          "Link strength, 0 to 1: 0.5 = no data; 0.83 = moderate support; about 0.5 with a narrow interval = data for and against balance."),
}


def tip(key: str, label: str) -> str:
    ru, en = TIPS[key]
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
        base = {"id": h, "title": title, "type": unit.get(h, {}).get("type"), "completion": unit.get(h, {}).get("primary_completion"),
                "outcome": it["outcome"], "scored": "P" in sc}
        if not it.get("card") or "P" not in sc:
            hyps[h] = base
            continue
        card = HypothesisCard.model_validate(it["card"])
        cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
        alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
        res = r32.evaluate(card, cvs, alts, fold=True, neutral_unverified=True)       # v3.3
        labels = r3.evaluate(card, cvs, alts, variant="v3.1").links
        by = {c.id: c for c in cvs}
        chain = []
        for cl in r3.chain(card):
            cv = by.get(cl.id)
            recs = []
            for side, lst in (("for", cv.evidence if cv else []), ("against", cv.counterevidence if cv else [])):
                for rec in lst:
                    w = r32.record_weight(rec, cl, side == "against")
                    if w <= 0:
                        continue
                    recs.append({"side": side, "pmid": rec.record_id.replace("PMID:", ""), "w": round(w, 3),
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
            F = r32.side_weight(cv.evidence if cv else [], ac, False, True)
            A = r32.side_weight(cv.counterevidence if cv else [], ac, True, True)
            S = r32.strength(F, A)[0]
            alt_rows.append({"id": alt.id, "text": f"{alt.subject.label} — {alt.relation.replace('_', ' ')} — {alt.object.label}",
                             "why": alt.rationale, "support": round(max(0.0, 2 * (S - 0.5)), 3),
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
        base_S = {c["id"]: (c["S"] if c["checked"] else 1.0) for c in chain}       # v3.3: links without data are neutral
        best_gain, raise_to, raise_link = 0.0, None, None
        for c in relevant:
            if c["S"] >= 5 / 6:
                continue
            P_new = p_product(card, {**base_S, c["id"]: 5 / 6})
            if P_new - res.P > best_gain:
                best_gain, raise_to, raise_link = P_new - res.P, round(P_new, 3), c["id"]
        de = card.decisive_experiment
        hyps[h] = {**base, "plain": card.claim_plain, "P": res.P, "P_lo": res.P_lo, "P_hi": res.P_hi, "I": res.I, "V": res.V,
                   "scope": res.scope, "gate": res.gate, "chain": chain, "alternatives": alt_rows,
                   "weakest": weakest["id"] if weakest else None, "strongest": strongest["id"] if strongest else None,
                   "P_if_weakest_moderate": raise_to, "raise_link": raise_link, "support_share": res.support_share, "coverage": res.coverage,
                   "unchecked": [c["id"] for c in chain if not c["checked"]], "experiment": {"design": de.design, "endpoint": de.endpoint, "n": de.n_planned},
                   "endpoint_clinical": sc.get("endpoint_clinical"), "trend_pubmed": sc.get("trend_pubmed"), "ai_role": sc.get("ai_role"),
                   "ai_span": card.ai_role_span, "aspid": {p: sc.get(f"aspid_{p}") for p in profiles},
                   "flags": res_flags(it)}
        values[h] = {"P": res.P, "I": res.I, "I_headroom": it["v3"].get("headroom_I"), "W": res.scope, "support_share": res.support_share, "coverage": res.coverage,
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
                                              "endpoint_clinical", "trend_pubmed", "ai_role", "support_share")}) for h in scored}
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
        card = HypothesisCard.model_validate(it["card"])
        cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
        alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
        ext = {k: values[h].get(k) for k in ("feasibility", "best_design_outcome", "independent_outcome", "against_share",
                                             "endpoint_clinical", "trend_pubmed", "ai_role")}
        hyps[h]["improvements"] = imp.items(card, cvs, alts, ext, values[h].get("I_headroom"))
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
details .body{padding:0 16px 14px}details.sub{border:0;background:transparent;margin:6px 0}details.sub>summary{padding:4px 0}.chip{display:inline-block;border-radius:999px;padding:1px 8px;font-size:.8rem;background:var(--idle-soft);margin:0 4px 4px 0}
.ok{background:var(--ok-soft)}.bad{background:var(--bad-soft)}.warn{background:var(--warn-soft)}
.chain{display:flex;flex-wrap:wrap;gap:6px;align-items:stretch;margin:8px 0}.link{border:1px solid var(--line);border-radius:8px;padding:6px 8px;min-width:150px;max-width:260px;font-size:.85rem}
.arrow{align-self:center;color:var(--muted)}.link .s{font-family:var(--mono)}
.up{color:var(--ok)}.down{color:var(--bad)}blockquote{margin:4px 0;padding-left:10px;border-left:3px solid var(--line);color:var(--muted);font-size:.85rem}
.tip{border-bottom:1px dotted var(--muted);cursor:help;position:relative}
.tip:hover::after,.tip:focus::after{position:absolute;left:0;top:calc(100% + 6px);z-index:20;width:min(320px,80vw);white-space:normal;
 background:var(--ink);color:var(--paper);font:400 .82rem/1.45 var(--body);padding:8px 10px;border-radius:8px;text-transform:none;letter-spacing:0;text-align:left}
html[data-lang="ru"] .tip:hover::after,html[data-lang="ru"] .tip:focus::after{content:attr(data-ru)}
html[data-lang="en"] .tip:hover::after,html[data-lang="en"] .tip:focus::after{content:attr(data-en)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.tabs button{font:inherit;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:4px 12px;cursor:pointer}
.tabs button[aria-selected="true"]{background:var(--accent);color:var(--surface);border-color:var(--accent)}
.ptab[hidden]{display:none}.cols{display:flex;gap:10px;flex-wrap:wrap;font-size:.85rem;margin:6px 0 8px;color:var(--muted)}.cols label{white-space:nowrap;cursor:pointer}
.hidecol{display:none}.pager{display:flex;gap:8px;align-items:center;margin:8px 0;font-size:.9rem}.pager button{font:inherit;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:6px;padding:2px 10px;cursor:pointer}
.tools{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:6px 0;font-size:.9rem}.tools input,.tools select{font:inherit;padding:3px 6px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink)}
tr.lead td:first-child{box-shadow:inset 3px 0 var(--accent)}.star{color:var(--accent);font-weight:600}
.steps{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:10px 0}.steps .st{border:1px solid var(--line);background:var(--surface);border-radius:8px;padding:6px 10px;font-size:.88rem;max-width:230px}
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
document.querySelectorAll('a[href^="#h-"]').forEach(a=>a.addEventListener('click',()=>{const d=document.querySelector(a.getAttribute('href'));if(d&&d.tagName==='DETAILS')d.open=true}));
"""


ITEM_CLS = {"rewrite": ("Можно исправить формулировкой", "Fixable by rewriting"),
            "research": ("Нужны новые данные", "Needs new data")}


def render_items(items: list[dict], profs: list[str]) -> str:
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
        "По запросу система применяет к выбранным гипотезам пункты «можно исправить формулировкой» из их разбора; улучшенный текст "
        "проходит ту же проверку с той же датой отсечения литературы. Эволюция не создаёт новых доказательств: рост P возможен только "
        "за счёт формулировки под уже найденные данные, рост I — это обещание дизайна. Улучшение пишется по находкам того же "
        "проверяющего, что его оценивает, поэтому рост оценки — подсказка, что менять, а не доказательство.",
        "On request the system applies to chosen hypotheses the \"fixable by rewriting\" items of their analysis; the improved text "
        "goes through the same checks with the same literature cut-off. Evolution makes no new evidence: P can rise only by fitting "
        "the text to what was found, I is a promise of design. The text is written from the findings of the verifier that then "
        "scores it, so a rise is a hint of what to change, not proof.") + '</p>']
    if pairs:
        out.append('<div class="scroll"><table class="tbl"><thead><tr><th>' + t("Гипотеза", "Hypothesis") + '</th><th>' +
                   t("Применено", "Applied") + '</th><th>P</th><th>I</th><th>' + tn(SHORT["support_share"]) + '</th>' +
                   "".join(f'<th>{tn(PROFILE_NAMES[p])}</th>' for p in profs) + '</tr></thead><tbody>')
        for u, p in pairs:
            c = p["compare"]
            def d(a, b):
                if a is None or b is None or isinstance(a, str):
                    return f'{e(a)} → {e(b)}'
                cls = "up" if b > a + 1e-3 else "down" if b < a - 1e-3 else "muted"
                return f'<span class="{cls}">{fmt(a)} → {fmt(b)}</span>'
            out.append(f'<tr><td class="title"><a href="#ev-{e(u)}">{e(H.get(u, {}).get("title", u)[:80])}</a><br><span class="muted mono">{e(u)}</span></td>'
                       f'<td class="mono">{e(", ".join(p.get("applied", [])))}</td>'
                       f'<td class="n">{d(*c["indicators"]["P"])}</td><td class="n">{d(*c["indicators"]["I"])}</td>'
                       f'<td class="n">{d(*c["indicators"]["support_share"])}</td>' +
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
            out.append(f'<details id="ev-{e(u)}"><summary>{e(H.get(u, {}).get("title", u)[:110])} <span class="muted mono">{e(u)}</span></summary><div class="body">')
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


def render(rep: dict) -> str:
    m, H = rep["meta"], rep["hyps"]
    out = ['<!doctype html><html lang="ru" data-lang="ru"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           f'<title>Отчёт по пулу — {e(m["pool"])}</title>',
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Literata:opsz,wght@7..72,400;7..72,600&family=Onest:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">',
           f'<style>{CSS}</style></head><body>']
    out.append('<header class="top"><div class="wrap"><b>hyp-arena</b><nav>'
               f'<a href="#read">{t("Как читать","How to read")}</a><a href="#table">{t("Рейтинг","Ranking")}</a>'
               f'<a href="#each">{t("Разбор гипотез","Each hypothesis")}</a>'
               + (f'<a href="#evo">{t("Эволюция","Evolution")}</a>' if rep.get("evolution") else "") +
               f'<a href="#app">{t("Приложения","Appendices")}</a></nav><span class="sp"></span>'
               '<button class="sw" onclick="setLang(\'ru\')">RU</button><button class="sw" onclick="setLang(\'en\')">EN</button>'
               '<button class="sw" onclick="setTheme()">◐</button></div></header><main class="wrap">')
    out.append(f'<p class="eyebrow" style="margin-top:24px">{t("Отчёт по пулу гипотез","Pool report")} · {e(m["date"])}</p>')
    out.append(f'<h1>{t(e(m["title_ru"]), e(m["title_en"]))}</h1>')
    out.append(f'<p class="prose muted">{t(e(m["about_ru"]), e(m["about_en"]))}</p>')
    out.append(f'<p class="muted mono" style="font-size:.8rem">{t("Метод","Method")} {e(m["method"])} · '
               f'{t("оценено","scored")} {m["n_scored"]} / {m["n"]} · {t("хеш оценок","scores SHA-256")} {e(m["sha"][:16])}…</p>')
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
        f"<b>2. Показатели.</b> Из записей код считает {tip('P','P — правдоподобие механизма')}, {tip('I','I — информативность эксперимента')}, "
        f"{tip('W','размах')} и ещё несколько показателей. Наведите на подчёркнутый термин, чтобы увидеть пояснение. Исход испытания "
        "метод <b>не предсказывает</b>: он оценивает, насколько обоснован механизм сейчас и что даст эксперимент.",
        f"<b>2. Indicators.</b> From the records the code computes {tip('P','P, plausibility of the mechanism')}, "
        f"{tip('I','I, informativeness of the experiment')}, {tip('W','scope')} and a few more. Hover over an underlined term "
        "for its meaning. The method does <b>not</b> predict the trial's result: it measures how well the mechanism is "
        "supported now and what the experiment would teach.") + '</p>')
    out.append('<p>' + t(
        "<b>3. Рейтинг — АСПИД.</b> Одного «правильного» веса у показателей нет: инвестору важнее одно, исследователю — другое. "
        "Поэтому задаётся только <b>профиль</b> — порядок важности (например, «правдоподобие важнее информативности, та — важнее "
        "размаха»), а точные веса разыгрываются:",
        "<b>3. Ranking: ASPID.</b> There is no single right weighting of the indicators: an investor cares about one thing, a "
        "researcher about another. So only a <b>profile</b> is set, an order of importance (e.g. \"plausibility above "
        "informativeness, informativeness above scope\"), and the exact weights are drawn:") + '</p></div>')
    out.append('<div class="steps">' + '<span class="arrow">→</span>'.join(f'<span class="st">{x}</span>' for x in [
        t("порядок важности профиля", "the profile's order of importance"),
        t("10 000 случайных наборов весов, совместимых с порядком", "10,000 random weight sets compatible with the order"),
        t("оценка каждой гипотезы в каждом наборе", "a score for each hypothesis in each set"),
        t(f"{tip('score','ожидаемая оценка')} → {tip('place','место')}; {tip('top5','вероятность топ-5')}",
          f"{tip('score','expected score')} → {tip('place','place')}; {tip('top5','probability of top 5')}")]) + '</div>')
    out.append('<p class="prose">' + t(
        "Очень низкое правдоподобие не компенсируется другими показателями. Вероятность топ-5 показывает, насколько место "
        "устойчиво: 0.9 — гипотеза в пятёрке почти при любых весах, 0.2 — только при некоторых.",
        "A very low plausibility is not compensated by the other indicators. The probability of top 5 shows how robust the place "
        "is: 0.9 means in the top 5 under almost any weights, 0.2 only under some.") + '</p>')
    # 2. ranking table per profile
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

    def cell(ind, x):
        v = x["values"].get(ind)
        if ind == "P":
            return (f'<td class="n" data-c="P" data-v="{x["P"]}">{fmt(x["P"])}<br><span class="muted" style="font-size:.78rem">'
                    f'{fmt(x["P_lo"])}–{fmt(x["P_hi"])}</span></td>')
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
                   f'<th>{tip("top5",t("Топ-5","Top 5"))}</th>' +
                   "".join(f'<th data-c="{ind}">{tip(ind, tn(SHORT.get(ind, (ind, ind))))}</th>' for ind in inds) + '</tr></thead><tbody>')
        for h in rep["ranks"][p]:
            x = H[h]
            rk = x["rank"][p]
            lead = rk <= 3
            why = ""
            if lead:
                ups = x["contrib"][p]["up"]
                why = '<br><span class="star">★ </span><span class="muted" style="font-size:.82rem">' + t("сильные стороны: ", "strengths: ") + \
                      (", ".join(tn(IND_NAMES.get(ind, (ind, ind))) for ind, _ in ups) or "—") + '</span>'
            q = e((x["title"] + " " + h).lower())
            out.append(f'<tr class="{"lead" if lead else ""}" data-type="{e(x.get("type"))}" data-q="{q}"><td class="n" data-v="{rk}">{rk}</td>'
                       f'<td class="title"><a href="#h-{e(h)}">{e(x["title"][:90])}</a><br><span class="muted mono">{e(h)}</span> · '
                       f'<span class="muted">{tn(TYPE_NAMES.get(x.get("type"), ("—","—")))}</span>{why}</td>'
                       f'<td class="n" data-v="{x["aspid"][p]}">{fmt(x["aspid"][p], 3)}</td><td class="n" data-v="{x["p_top5"][p]}">{fmt(x["p_top5"][p])}</td>' +
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
    out.append(f'<h2 id="each">{t("Разбор каждой гипотезы","Each hypothesis")}</h2><p class="muted">' + t(
        "Раскройте строку. Полное разложение по звеньям с цитатами — в приложении Б.",
        "Open a row. The full breakdown by links with quotes is in appendix B.") + '</p>')
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
        rows = [("P", f'<span class="mono">{fmt(x["P"])} [{fmt(x["P_lo"])}; {fmt(x["P_hi"])}]</span>'),
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
        out.append(render_items(x.get("improvements") or [], profs))
        out.append('</div></details>')
    if rep.get("evolution"):
        out.append(render_evolution(rep["evolution"], H, profs))
    # 5. appendices
    out.append(f'<h2 id="app">{t("Приложения","Appendices")}</h2>')
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
    out.append('<details><summary><b>' + t("Б. Полное разложение по гипотезам","B. Full breakdown per hypothesis") + '</b></summary><div class="body">')
    for h in order:
        x = H[h]
        if x.get("P") is None:
            continue
        out.append(f'<details><summary>{e(x["title"][:110])} <span class="muted mono">{e(h)}</span></summary><div class="body">')
        out.append(f'<p class="muted">{t("Заявленный эксперимент: ","Stated experiment: ")}{e(x["experiment"]["design"])}, '
                   f'{e(x["experiment"]["endpoint"] or "—")}; n {e(x["experiment"]["n"] or "—")}; '
                   f'{t("завершение","completion")} {e(x.get("completion") or "—")}</p>')
        for c in x["chain"]:
            out.append(f'<h3 id="b-{e(h)}-{e(c["id"])}">{tn(LINK_NAMES.get(c["link"], (c["link"],)*2))}: {e(c["text"])}</h3>'
                       f'<p class="mono muted">S {fmt(c["S"],3)} [{fmt(c["lo"])}; {fmt(c["hi"])}] · F {fmt(c["F"],3)} · A {fmt(c["A"],3)} · {e(c["label"])}'
                       + (f' · {t("признак старения","hallmark")}: {e(c["hallmark"])}' if c["hallmark"] else "") + '</p>')
            if not c["records"]:
                out.append(f'<p class="muted">{t("Записей нет: литература до даты оценки не нашла данных по этому звену.","No records: the literature before the date of scoring had no data on this link.")}</p>')
                continue
            out.append('<div class="scroll"><table class="tbl"><thead><tr><th>PMID</th><th>' + t("за / против","for / against") +
                       '</th><th>' + t("вес","weight") + '</th><th>' + t("дизайн","design") + '</th><th>n</th><th>' +
                       t("эффект","effect") + '</th><th>' + t("цитата","quote") + '</th></tr></thead><tbody>')
            for r in c["records"][:12]:
                out.append(f'<tr><td><a href="https://pubmed.ncbi.nlm.nih.gov/{e(r["pmid"])}/" target="_blank" rel="noopener">{e(r["pmid"])}</a></td>'
                           f'<td><span class="chip {"ok" if r["side"]=="for" else "bad"}">{t("за","for") if r["side"]=="for" else t("против","against")}</span></td>'
                           f'<td class="n">{fmt(r["w"],3)}</td><td>{e(r["design"])}</td><td class="n">{e(r["n"] or "—")}</td>'
                           f'<td>{e((r["effect"] or "")[:80])}</td><td><blockquote>{e((r["quote"] or "")[:400])}</blockquote></td></tr>')
            out.append('</tbody></table></div>')
            if len(c["records"]) > 12:
                out.append(f'<p class="muted">… {t("ещё","and")} {len(c["records"]) - 12}</p>')
        if x["alternatives"]:
            out.append('<h3>' + t("Альтернативные объяснения","Alternative explanations") + '</h3><ul>' + "".join(
                f'<li>{e(a["text"])} — {t("поддержка","support")} {fmt(a["support"])}; {t("эксперимент при успехе: ","experiment if positive: ")}{e(a["on_positive"])}<br>'
                f'<span class="muted">{e(a["why"] or "")}</span></li>' for a in x["alternatives"]) + '</ul>')
        out.append('<h3>' + t("Остальные показатели (справочно)","Other indicators (for reference)") + '</h3><p class="mono" style="font-size:.85rem">' +
                   " · ".join(f'{e(i)} {round(v*100) if v is not None else "—"}%' for i, v in sorted(x["pct"].items())) +
                   f'</p><p class="muted" style="font-size:.85rem">{t("Проценты — доля пула ниже этой гипотезы по показателю.","Percent: share of the pool below this hypothesis on the indicator.")}</p>')
        if x.get("ai_span"):
            out.append(f'<p>{t("Роль ИИ — цитата: ","AI role, quote: ")}<blockquote>{e(x["ai_span"])}</blockquote></p>')
        out.append('</div></details>')
    out.append('</div></details>')
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
    out.append(f'</main><script>{JS}</script></body></html>')
    return "\n".join(out)


def prospective(n: int = 60) -> tuple[dict, str]:
    from scripts.ctgov_outcomes import KG
    d = KG / "hypothesis_sources" / "prospective"
    run = json.loads((d / f"run_{n}.json").read_text())
    sb = (d / f"scores_{n}.json").read_bytes()
    texts = {json.loads(l)["id"]: json.loads(l)["text"] for l in open(d / f"texts_{n}.jsonl")}
    meta = {"pool": f"prospective-{n}", "date": "2026-11-06", "sha": hashlib.sha256(sb).hexdigest(),
            "method": "v3.3 (fold, links without records neutral, support share), normalize_card/v10, verify_claim/v9, ASPID: evidence trial-3, evolution trial-2, funding trial-4",
            "title_ru": f"Проспективный пул: {n} идущих испытаний", "title_en": f"Prospective pool: {n} ongoing trials",
            "about_ru": "Испытания на ClinicalTrials.gov, где среди состояний — само старение, с завершением в ноябре 2026 — декабре 2028; "
                        "по 15 на тип вмешательства. Оценены до появления результатов; оценки зафиксированы хешем.",
            "about_en": "ClinicalTrials.gov trials with ageing itself among the conditions, primary completion November 2026 – December 2028; "
                        "15 per intervention type. Scored before any result; the scores are frozen with a hash."}
    rep = build(run, json.loads(sb), json.loads((d / f"units_{n}.json").read_text()), texts, meta)
    evo_p = d / f"evolution_{n}.json"
    if evo_p.exists():
        from hyparena.card import evolve_v3
        evo = json.loads(evo_p.read_text())["pairs"]
        for u, p in evo.items():
            child = (p.get("child_run") or {}).get("items", [{}])[0]
            if child and u in rep["hyps"] and "values" in rep["hyps"][u]:
                v = rep["hyps"][u]["values"]
                pe = {k: v.get(k) for k in ("feasibility", "best_design_outcome", "independent_outcome", "against_share",
                                            "endpoint_clinical", "trend_pubmed", "ai_role")}
                ce = {**pe, "endpoint_clinical": p.get("child_endpoint"), "ai_role": (child.get("card") or {}).get("ai_role", pe.get("ai_role"))}
                p["compare"] = evolve_v3.compare(run[u]["items"][0], child, pe, ce)
        rep["evolution"] = evo
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

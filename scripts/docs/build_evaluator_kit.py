"""Build the standalone Method v4.0 evaluator code archive (.zip).

Packages `hyparena/`, `configs/`, `manual.md`, `changelog-v4.0.md`, `dossier-instructions-draft.md`,
`calculate.py`, `make_report.py`, `example_cases.json`, `requirements.txt`, and Russian `README.md`
into a self-contained zip archive for external/blinded hypothesis evaluation.

Usage:
    python scripts/docs/build_evaluator_kit.py --out path/to/hyp-arena-v4.0-evaluation-kit.zip [--cutoff 2026-11-27]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CONFIG_FILES = (
    "compound_aliases.yaml",
    "disease_models.yaml",
    "lifespan_medians.yaml",
    "profiles.yaml",
    "profiles_v3.yaml",
    "v4-flash.yaml",
)

REQUIREMENTS_TXT = """pydantic>=2,<3
numpy
scipy
PyYAML
httpx
"""

CALCULATE_PY = '''"""Structured evidence -> Method v4.0 calculations + ASPID profile rankings and cluster deduplication."""
import argparse
import json
from pathlib import Path

from hyparena import METHOD_V4_VERSION
from hyparena.card.models import ClaimVerification, HypothesisCard
from hyparena.novelty.novelty_v34 import link_levels, novelty, novelty_source
from hyparena.reading.implementation import is_non_drug, revalidate_saved
from hyparena.reports import diversity as div_mod
from hyparena.scoring import aspid_v3, rules_v3, rules_v32, rules_v4
from hyparena.scoring.v3_extra import (
    endpoint_for_experiment,
    extras,
    feasibility,
    feasibility_breakdown,
    feasibility_diagnostic,
)

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("cases", help="JSON array of structured cases (see example_cases.json)")
p.add_argument("--as-of", default="", help="Literature cutoff YYYY-MM-DD for PubMed / ClinicalTrials.gov readiness checks")
args = p.parse_args()

cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
results = {}
cards_for_clusters = {}
aspid_axes = {}

for case in cases:
    ident = case["id"]
    card_raw = HypothesisCard.model_validate(case["card"])
    cvs_raw = [ClaimVerification.model_validate(c) for c in case["verifications"]]
    alts = {k: ClaimVerification.model_validate(v) for k, v in (case.get("alternatives") or {}).items()}
    exp_text = case.get("experiment_text") or case.get("hypothesis_text") or card_raw.decisive_experiment.span or ""

    raw_impl = case.get("implementation_readiness")
    impl = None
    if isinstance(raw_impl, dict) and ("component_checks" in raw_impl or is_non_drug(card_raw)):
        impl = revalidate_saved(
            raw_impl,
            args.as_of,
            experiment_text=exp_text,
            n_planned=card_raw.decisive_experiment.n_planned,
        )

    r4 = rules_v4.evaluate(
        card_raw,
        cvs_raw,
        alts,
        implementation=impl,
        as_of=args.as_of,
        experiment_text=exp_text,
    )
    card_v4, cvs_v4, alts_v4, _, _ = rules_v4.prepare_for_v4(card_raw, cvs_raw, alts, experiment_text=exp_text)
    base_v32 = rules_v32.evaluate(card_v4, cvs_v4, alts_v4, v36=True)
    v31_dict = rules_v3.evaluate(card_v4, cvs_v4, alts_v4, variant="v3.1").as_dict()
    ext = extras(card_v4, cvs_v4, v31_dict, args.as_of, implementation=impl)
    po = case.get("paper_outcomes")
    ind_in = case.get("indicators") or {}
    ep = endpoint_for_experiment(
        ind_in.get("endpoint_clinical"),
        card_v4.decisive_experiment.system,
        card=card_v4,
        implementation=impl,
    )
    nov = novelty(card_v4, cvs_v4, base_v32, absence=case.get("absence"), paper_outcomes=po)
    feas = feasibility(card_v4, as_of=args.as_of, implementation=impl)

    results[ident] = {
        "method": METHOD_V4_VERSION,
        "aspid": {},
        "cluster_id": None,
        "cluster_peers": [],
        "gate": r4.gate,
        "gate_reason": r4.gate_reason,
        "resource_tier": r4.resource_tier,
        "worst_domain_risk": r4.worst_domain_risk,
        "chain_state": r4.chain_state,
        "support_share": r4.support_share,
        "coverage": r4.coverage,
        "I": r4.I,
        "headroom_I": r4.headroom_I,
        "scope": r4.scope,
        "novelty": nov,
        "novelty_source": novelty_source(card_v4, cvs_v4, paper_outcomes=po),
        "link_novelty": link_levels(card_v4, cvs_v4),
        "feasibility": feas,
        "feasibility_breakdown": feasibility_breakdown(card_v4, as_of=args.as_of, implementation=impl),
        "feasibility_diagnostic": feasibility_diagnostic(card_v4, as_of=args.as_of, implementation=impl),
        "endpoint_clinical": ep,
        "chain_summary": r4.chain_summary,
        "evaluation_v4": r4.as_dict(),
        "legacy_non_refutation": {"P": r4.P, "V_legacy": r4.V, "note": "P and V are legacy non-refutation diagnostics; ranking uses ASPID profiles over chain_state, N, I, W, feasibility, endpoint_clinical."},
    }
    if r4.gate == "pass":
        cards_for_clusters[ident] = card_raw
        aspid_axes[ident] = (
            {"P": r4.P, "scope": r4.scope, "I": r4.I, "headroom_I": r4.headroom_I, "gate": "pass"},
            {
                "feasibility": feas,
                "best_design_outcome": ext.get("best_design_outcome"),
                "independent_outcome": ext.get("independent_outcome"),
                "against_share": ext.get("against_share"),
                "endpoint_clinical": ep,
                "trend_pubmed": ind_in.get("trend_pubmed"),
                "ai_role": ind_in.get("ai_role") or card_v4.ai_role,
                "support_share": r4.support_share,
                "chain_state": r4.chain_state,
                "N": nov,
            },
        )

profiles = aspid_v3.load()
ranks_by_profile = {}
if aspid_axes:
    scored_ids = list(aspid_axes.keys())
    for prof_name in profiles:
        agg = aspid_v3.rank(aspid_axes, prof_name, K=10000)
        order = sorted(scored_ids, key=lambda h: -round(agg.expected[h], 4))
        ranks_by_profile[prof_name] = order
        for place, h in enumerate(order, 1):
            results[h]["aspid"][prof_name] = {
                "score": round(agg.expected[h], 4),
                "place": place,
                "of": len(scored_ids),
                "p_top5": round(agg.p_topk[h], 3),
            }

cinfo = div_mod.pool_clusters(cards_for_clusters, ranks_by_profile)
for h in results:
    results[h]["cluster_id"] = cinfo["cluster_of"].get(h)
    results[h]["cluster_peers"] = cinfo["peers_of"].get(h, [])

results["_pool_summary"] = {
    "method": METHOD_V4_VERSION,
    "n_cases": len(cases),
    "n_ranked": len(aspid_axes),
    "ranks": ranks_by_profile,
    "clusters": cinfo["clusters"],
    "top_distinct": cinfo["top_distinct"],
}
print(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False))
'''

MAKE_REPORT_PY = '''"""Create a 5-tab Russian HTML report from manually prepared cases (Method v4.0)."""
import argparse
import hashlib
import json
from pathlib import Path

from hyparena import METHOD_V4_VERSION
from hyparena.card.models import ClaimVerification, HypothesisCard
from hyparena.reading.implementation import is_non_drug, revalidate_saved
from hyparena.reports.report_html import build
from hyparena.reports.report_v2 import render
from hyparena.scoring import rules_v3, rules_v4

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("cases", help="JSON array as in example_cases.json")
p.add_argument("--as-of", required=True, help="Literature cutoff YYYY-MM-DD")
p.add_argument("--out", required=True, help="HTML output path in private storage")
p.add_argument("--hypotheses", type=Path, help="Optional original judge_hypotheses_blind.json for the card text")
a = p.parse_args()

raw = Path(a.cases).read_bytes()
cases = json.loads(raw)
originals = {}
if a.hypotheses:
    source = json.loads(a.hypotheses.read_text(encoding="utf-8"))
    if source["as_of"] != a.as_of:
        p.error("original hypotheses must have the same cutoff as the report")
    rows = source["hypotheses"]
    originals = {row["id"]: row for row in rows}
    if len(originals) != len(rows) or set(originals) != {case["id"] for case in cases}:
        p.error("original hypothesis IDs must be unique and match the cases")

run, scores, units, texts = {}, {}, [], {}
for case in cases:
    ident = case["id"]
    if ident in run:
        raise ValueError(f"duplicate id: {ident}")
    card_raw = HypothesisCard.model_validate(case["card"])
    cvs_raw = [ClaimVerification.model_validate(x) for x in case["verifications"]]
    alts = {k: ClaimVerification.model_validate(v) for k, v in (case.get("alternatives") or {}).items()}

    text_val = case.get("hypothesis_text", card_raw.claim_plain)
    if ident in originals:
        original = originals[ident]
        fields = (("Тезис", "claim"), ("Обоснование", "rationale"), ("Эксперимент", "experiment"))
        text_val = "\\n\\n".join(f"{label} — {original[key]}" for label, key in fields if original.get(key))
    texts[ident] = text_val
    exp_text = case.get("experiment_text") or text_val or card_raw.decisive_experiment.span or ""

    raw_impl = case.get("implementation_readiness")
    impl = None
    if isinstance(raw_impl, dict) and ("component_checks" in raw_impl or is_non_drug(card_raw)):
        impl = revalidate_saved(
            raw_impl,
            a.as_of,
            experiment_text=exp_text,
            n_planned=card_raw.decisive_experiment.n_planned,
        )

    card_v4, cvs_v4, alts_v4, _, _ = rules_v4.prepare_for_v4(card_raw, cvs_raw, alts, experiment_text=exp_text)
    old = rules_v3.evaluate(card_v4, cvs_v4, alts_v4, variant="v3.1").as_dict()
    r4 = rules_v4.evaluate(
        card_raw,
        cvs_raw,
        alts,
        implementation=impl,
        as_of=a.as_of,
        experiment_text=exp_text,
    )

    item = {
        "outcome": "unknown",
        "card": case["card"],
        "verification": {"claims": case["verifications"]},
        "v3_alternatives": case.get("alternatives") or {},
        "v3": old,
    }
    if case.get("paper_outcomes"):
        item["paper_outcomes"] = case["paper_outcomes"]
    if impl is not None:
        item["implementation_readiness"] = impl
    if case.get("absence"):
        item["absence"] = case["absence"]

    run[ident] = {"items": [item], "meta": {"as_of": a.as_of}}
    scores[ident] = {"P": r4.P}
    for key in ("endpoint_clinical", "trend_pubmed", "ai_role"):
        if key in (case.get("indicators") or {}):
            scores[ident][key] = case["indicators"][key]
    units.append({"id": ident})

meta = {
    "pool": "Подготовленные карточки",
    "date": a.as_of,
    "title_ru": "Отчёт по подготовленным данным (метод v4.0)",
    "title_en": "Report from prepared data (Method v4.0)",
    "about_ru": "Ручная подготовка исходных данных по методу v4.0; полнота поиска и цитаты требуют отдельной проверки.",
    "about_en": "Manually prepared input under Method v4.0; search coverage and quotations require independent checking.",
    "method": METHOD_V4_VERSION,
    "sha": hashlib.sha256(raw).hexdigest(),
}
report = build(run, scores, units, texts, meta)
Path(a.out).write_text(render(report), encoding="utf-8")
'''


def _readme_md(cutoff: str) -> str:
    return f"""# Пакет автономной оценки по мануалу HypArena v4.0 · {cutoff}

Пакет предназначен для независимой оценки гипотез на срез **`{cutoff}`** (или иной заданный `--as-of YYYY-MM-DD`) по **методу v4.0**.
Полные правила изложены в `manual.md`, сводка всех изменений выпуска — в `changelog-v4.0.md`, требования к общему досье для слепых судей — в `dossier-instructions-draft.md`.

Подготовьте `cases.json` по образцу `example_cases.json`, рассчитайте `results.json` через `calculate.py` и соберите пятистраничный русскоязычный отчёт `report.html` через `make_report.py`. Отдельно сформируйте единый `dossier.json` по `dossier-instructions-draft.md`.

---

## Что нового в `cases.json` для метода v4.0

1. **Явные роли звеньев (`card.claims[].chain_roles` / `chain_role`) и отделение предпосылок от M2:**
   - Каждому утверждению задаётся `chain_roles` (и/или `chain_role`) из закрытого списка `{{background, mechanism, novel_contribution, outcome}}`: `background` — известная биологическая/клиническая предпосылка, `mechanism` — промежуточный причинный шаг, `novel_contribution` — заявляемый новый вклад гипотезы, `outcome` — основной проверяемый исход.
   - Утверждения с ролью `"background"` **не входят в среднее баланса доказательств `chain_state` (M2)**, чтобы хрестоматийные факты не раздували оценку спекулятивной догадки, но проходят отдельный порог опровержения (`gate = "refuted_background"` при опровержении предпосылки РКИ/метаанализом в релевантном контексте).

2. **Точность спецификации и решающий контраст (`card.decisive_experiment`):**
   - `decisive_contrast_span` — дословный фрагмент текста протокола с решающим межгрупповым сравнением (не путать с ожидаемым направлением результата).
   - `target_engagement_span` — дословный фрагмент о прямом замере связывания/активности мишени (если есть в протоколе).
   - `precision_status` — `"stated_for_contrast"`, `"general_principle_only"` или `"missing"`; `tested_scope` — область действия эксперимента (`"direct"`, `"prerequisite"`, `"unclear"`).

3. **Отношение статьи к утверждению (`relation_to_claim` в записях `verifications`):**
   - В `evidence` / `counterevidence` каждой записи можно явно задать `relation_to_claim`: `"direct_support"`, `"direct_contradiction"`, `"related"`, `"irrelevant"` или `"insufficient"`.
   - Фильтр кода `enforce_relation_to_claim` отбрасывает `"irrelevant"` и `"insufficient"`, а записи `"related"` ограничивает сверху смежным контекстом.

4. **Альтернативы, методологические лазейки и нулевой исход (`card.proposed_alternatives`):**
   - Для каждой альтернативы указываются `control_span` (дословный фрагмент протокола о контроле/группе), `loophole` (непустая строка с описанием открытой лазейки, либо `""` / `"none"` при её отсутствии), `loophole_ruled_out_why` и при необходимости `conditional_on_negative` (`"eliminated"` / `"weakened"` / `"unchanged"`).
   - Код (`ground_discrimination_v4`) понижает `eliminated` до `weakened` (`d <= 0.5`), если `control_span` отсутствует дословно или указана не закрытая дизайном `loophole` (например, пассивный контроль не закрывает системный плейотропный эффект). Условное отсечение на нулевом исходе сохраняется как диагностика только при дословном `target_engagement_span`.

5. **Трёхкомпонентная готовность по слабому звену (`implementation_readiness` v2 и `resource_tier`):**
   - Вместо одного флага готовности `implementation_readiness` в v4.0 содержит `resource_tier` (`"1_in_vitro"`, `"2_animal"`, `"3_human_ex_vivo_or_pilot"`, `"4_clinical_in_vivo"`), `overall_evidence_status` и массив `component_checks` по трём компонентам:
     - `delivery_or_intervention` (доставка/режим вмешательства в целевую ткань/систему),
     - `population_or_model` (доступ к популяции, линии или первичной модели),
     - `measurement_or_assay` (валидированный метод измерения / биопсия / ассей).
   - Каждый компонент со статусом `"confirmed_in_context"` (`1.0`) или `"adjacent_only"` (`0.5`) обязан иметь дословную цитату `evidence_quote` из заголовка/аннотации `evidence_pmid` не позже `--as-of` (либо из текста протокола для стандартных рутинных процедур). Неподтверждённая цитата автоматически переводится в `"insufficient"` (`0.0`).
   - В расчёт реализуемости идёт **слабое звено** `min_readiness_score` по применимым компонентам (и ограничивает сверху регуляторный статус соединения, если узким местом протокола является инвазивный замер или доставка). Прежний формат `v1` (`verified_status`) также поддерживается для обратной совместимости.

6. **`paper_outcomes` и `absence`:**
   - Работают так же, как в `v3.13`: `paper_outcomes` фиксирует дословные функциональные/клинические исходы того же вмешательства из ранних звеньев при пустом слоте исхода, а `absence` задаёт проверенные кодом подсчёты пар терминов в PubMed до `--as-of` для уровня `new_mechanism`.

---

## Быстрый старт и проверка

```sh
python -m pip install -r requirements.txt

# Проверка на встроенном примере (работает полностью автономно):
python calculate.py example_cases.json --as-of {cutoff} > example_results.json
python make_report.py example_cases.json --as-of {cutoff} --out example_report.html

# Расчёт рабочего пула:
python calculate.py cases.json --as-of {cutoff} > results.json
python make_report.py cases.json --as-of {cutoff} --hypotheses judge_hypotheses_blind.json --out report.html
```

При передаче `--hypotheses judge_hypotheses_blind.json` все идентификаторы гипотез и поле `"as_of"` во входном файле должны совпадать с `cases.json` и параметром `--as-of`.
"""


def _example_cases() -> list[dict]:
    exp_s1 = (
        "Randomised double-blind placebo-controlled trial in 120 older adults (65-80 years) comparing "
        "oral compound-X 50 mg daily versus matching placebo capsules for 16 weeks; primary endpoint is "
        "6-minute walk distance, with skeletal muscle phospho-AMPK measured at week 4 as target engagement."
    )
    exp_s2 = (
        "Open-label two-arm mouse study (n=40 aged C57BL/6 mice) comparing structured treadmill training "
        "versus sedentary cage control for 12 weeks; primary outcome is rotarod latency."
    )
    return [
        {
            "id": "S1",
            "hypothesis_text": (
                "AMPK activity declines in aged skeletal muscle. Oral compound-X selectively activates "
                "skeletal-muscle AMPK without mitochondrial complex I inhibition and improves 6-minute walk "
                "distance in older adults."
            ),
            "experiment_text": exp_s1,
            "card": {
                "id": "S1",
                "hypothesis_type": "interventional",
                "claim_plain": "Oral compound-X activates muscle AMPK and improves 6-minute walk distance in older adults.",
                "pico": {
                    "population": {"taxon": "Homo sapiens", "label": "older adults 65-80 years", "sex": "both", "age_at_start": "65-80 years", "condition": "age-related mobility decline", "span": "older adults (65-80 years)"},
                    "intervention": [{"label": "rapamycin", "type": "compound", "dose": "50 mg", "regimen": "daily", "route": "oral", "span": "oral compound-X 50 mg daily"}],
                    "comparator": {"type": "placebo", "label": "matching placebo capsules", "span": "versus matching placebo capsules"},
                    "outcome": {"endpoint": "healthspan", "metric": "6-minute walk distance", "direction": "increase", "span": "improves 6-minute walk distance"},
                    "time": "16 weeks",
                },
                "claims": [
                    {
                        "id": "c0",
                        "subject": {"label": "aging"},
                        "relation": "decreases_expression",
                        "object": {"label": "AMPK activity", "hallmark": "deregulated_nutrient_sensing"},
                        "qualifiers": {"species": "human", "tissue": "skeletal muscle"},
                        "role": "premise",
                        "chain_role": "background",
                        "chain_roles": ["background"],
                        "link": "pathway",
                        "source_span": "AMPK activity declines in aged skeletal muscle",
                    },
                    {
                        "id": "c1",
                        "subject": {"label": "rapamycin"},
                        "relation": "activates",
                        "object": {"label": "AMPK", "hallmark": "deregulated_nutrient_sensing"},
                        "qualifiers": {"species": "human", "tissue": "skeletal muscle"},
                        "role": "mechanism",
                        "chain_role": "novel_contribution",
                        "chain_roles": ["mechanism", "novel_contribution"],
                        "link": "engagement",
                        "source_span": "selectively activates skeletal-muscle AMPK",
                    },
                    {
                        "id": "c2",
                        "subject": {"label": "rapamycin"},
                        "relation": "improves_healthspan_in",
                        "object": {"label": "older adults"},
                        "qualifiers": {"species": "human", "measure": "6-minute walk distance"},
                        "role": "outcome",
                        "chain_role": "outcome",
                        "chain_roles": ["outcome"],
                        "link": "outcome",
                        "source_span": "improves 6-minute walk distance in older adults",
                    },
                ],
                "decisive_experiment": {
                    "system": "human",
                    "endpoint": "function",
                    "duration_class": "months",
                    "design": "rct",
                    "control": "placebo",
                    "n_planned": 120,
                    "primary_outcome": "6-minute walk distance",
                    "duration": "16 weeks",
                    "decisive_contrast_span": "comparing oral compound-X 50 mg daily versus matching placebo capsules",
                    "target_engagement_span": "skeletal muscle phospho-AMPK measured at week 4 as target engagement",
                    "precision_status": "stated_for_contrast",
                    "tested_scope": "direct",
                    "span": exp_s1,
                },
                "proposed_alternatives": [
                    {
                        "id": "p1",
                        "subject": {"label": "expectation and clinic attention"},
                        "relation": "improves_healthspan_in",
                        "object": {"label": "6-minute walk distance"},
                        "rationale": "Supervised clinic visits and expectation can increase walk performance.",
                        "support_pmids": ["9"],
                        "on_positive": "eliminated",
                        "on_negative": "unchanged",
                        "conditional_on_negative": "eliminated",
                        "control_span": "matching placebo capsules",
                        "target_engagement_span": "skeletal muscle phospho-AMPK measured at week 4 as target engagement",
                        "loophole": "",
                        "loophole_ruled_out_why": "Double-blind matching placebo equalises clinic visits and expectation.",
                        "role": "alternative",
                    }
                ],
                "ai_role": "none",
            },
            "verifications": [
                {
                    "id": "c0",
                    "evidence": [
                        {
                            "source": "PubMed",
                            "record_id": "PMID:10",
                            "lab_or_cohort": "PMID:10",
                            "species": "human",
                            "quote": "AMPK phosphorylation is lower in aged human muscle.",
                            "quote_role": "finding",
                            "qualifiers_match": {"intervention_match": "exact"},
                            "relation_to_claim": "direct_support",
                            "design": "observational",
                            "n_total": 80,
                            "comparison": "between_groups",
                            "effect_class": "medium",
                        }
                    ],
                },
                {
                    "id": "c1",
                    "evidence": [
                        {
                            "source": "PubMed",
                            "record_id": "PMID:1",
                            "lab_or_cohort": "PMID:1",
                            "species": "mouse",
                            "quote": "Compound activation increased muscle p-AMPK two-fold.",
                            "quote_role": "finding",
                            "qualifiers_match": {"intervention_match": "same_class"},
                            "relation_to_claim": "direct_support",
                            "design": "animal",
                            "n_total": 40,
                            "comparison": "between_groups",
                            "effect_class": "large",
                        }
                    ],
                },
                {
                    "id": "c2",
                    "evidence": [
                        {
                            "source": "PubMed",
                            "record_id": "PMID:3",
                            "lab_or_cohort": "PMID:3",
                            "species": "human",
                            "quote": "mTOR/AMPK modulation improved walking performance in older adults.",
                            "quote_role": "finding",
                            "qualifiers_match": {"intervention_match": "same_class"},
                            "relation_to_claim": "direct_support",
                            "design": "rct",
                            "n_total": 120,
                            "comparison": "between_groups",
                            "effect_class": "medium",
                        }
                    ],
                },
            ],
            "alternatives": {
                "p1": {
                    "id": "p1",
                    "evidence": [
                        {
                            "source": "PubMed",
                            "record_id": "PMID:9",
                            "lab_or_cohort": "PMID:9",
                            "quote": "Placebo-controlled trials isolate expectation effects in walk tests.",
                            "quote_role": "finding",
                            "qualifiers_match": {"intervention_match": "exact"},
                            "design": "observational",
                            "n_total": 300,
                            "comparison": "between_groups",
                            "effect_class": "medium",
                        }
                    ],
                }
            },
            "implementation_readiness": {
                "resource_tier": "4_clinical_in_vivo",
                "overall_evidence_status": "confirmed_in_context",
                "component_checks": [
                    {
                        "component": "delivery_or_intervention",
                        "target_system": "human oral dosing",
                        "evidence_status": "confirmed_in_context",
                        "evidence_pmid": "",
                        "evidence_quote": "oral compound-X 50 mg daily versus matching placebo capsules",
                        "notes": "Standard oral capsule regimen stated in protocol.",
                    },
                    {
                        "component": "population_or_model",
                        "target_system": "older adults 65-80 years",
                        "evidence_status": "confirmed_in_context",
                        "evidence_pmid": "",
                        "evidence_quote": "120 older adults (65-80 years)",
                        "notes": "Community-dwelling older adult cohort.",
                    },
                    {
                        "component": "measurement_or_assay",
                        "target_system": "6-minute walk distance and week-4 muscle phospho-AMPK",
                        "evidence_status": "adjacent_only",
                        "evidence_pmid": "",
                        "evidence_quote": "skeletal muscle phospho-AMPK measured at week 4",
                        "notes": "Requires repeated needle muscle biopsy in older adults.",
                    },
                ],
            },
            "indicators": {"endpoint_clinical": "function", "trend_pubmed": 0.25, "ai_role": "none"},
            "paper_outcomes": [],
        },
        {
            "id": "S2",
            "hypothesis_text": (
                "Structured treadmill training upregulates PGC-1alpha in skeletal muscle and increases "
                "rotarod latency in aged mice."
            ),
            "experiment_text": exp_s2,
            "card": {
                "id": "S2",
                "hypothesis_type": "interventional",
                "claim_plain": "Structured treadmill training increases muscle PGC-1alpha and rotarod latency in aged mice.",
                "pico": {
                    "population": {"taxon": "Mus musculus", "label": "aged C57BL/6 mice", "strain": "C57BL/6", "sex": "both", "age_at_start": "20 months", "span": "aged C57BL/6 mice"},
                    "intervention": [{"label": "treadmill training", "type": "exercise", "regimen": "12 weeks", "span": "structured treadmill training"}],
                    "comparator": {"type": "none", "label": "sedentary cage control", "span": "versus sedentary cage control"},
                    "outcome": {"endpoint": "healthspan", "metric": "rotarod latency", "direction": "increase", "span": "primary outcome is rotarod latency"},
                    "time": "12 weeks",
                },
                "claims": [
                    {
                        "id": "c1",
                        "subject": {"label": "treadmill training"},
                        "relation": "increases_expression",
                        "object": {"label": "PGC-1alpha", "hallmark": "mitochondrial_dysfunction"},
                        "qualifiers": {"species": "mouse", "tissue": "skeletal muscle"},
                        "role": "mechanism",
                        "chain_role": "mechanism",
                        "chain_roles": ["mechanism"],
                        "link": "pathway",
                        "source_span": "upregulates PGC-1alpha in skeletal muscle",
                    },
                    {
                        "id": "c2",
                        "subject": {"label": "treadmill training"},
                        "relation": "improves_healthspan_in",
                        "object": {"label": "aged mice"},
                        "qualifiers": {"species": "mouse", "measure": "rotarod latency"},
                        "role": "outcome",
                        "chain_role": "outcome",
                        "chain_roles": ["outcome"],
                        "link": "outcome",
                        "source_span": "increases rotarod latency in aged mice",
                    },
                ],
                "decisive_experiment": {
                    "system": "mouse",
                    "endpoint": "biomarker",
                    "duration_class": "months",
                    "design": "other",
                    "control": "none",
                    "n_planned": 40,
                    "primary_outcome": "rotarod latency",
                    "duration": "12 weeks",
                    "decisive_contrast_span": "comparing structured treadmill training versus sedentary cage control",
                    "precision_status": "stated_for_contrast",
                    "tested_scope": "direct",
                    "span": exp_s2,
                },
                "proposed_alternatives": [
                    {
                        "id": "p1",
                        "subject": {"label": "handling stress and novelty arousal"},
                        "relation": "improves_healthspan_in",
                        "object": {"label": "rotarod latency"},
                        "rationale": "Daily handling in the treadmill arm vs unhandled cage control can alter arousal and motor coordination.",
                        "support_pmids": ["12"],
                        "on_positive": "eliminated",
                        "on_negative": "unchanged",
                        "control_span": "sedentary cage control",
                        "loophole": "Passive sedentary cage control does not match daily handling and apparatus exposure.",
                        "loophole_ruled_out_why": "",
                        "role": "alternative",
                    }
                ],
                "ai_role": "none",
            },
            "verifications": [
                {
                    "id": "c1",
                    "evidence": [
                        {
                            "source": "PubMed",
                            "record_id": "PMID:11",
                            "lab_or_cohort": "PMID:11",
                            "species": "mouse",
                            "quote": "Endurance treadmill training elevated muscle PGC-1alpha in aged mice.",
                            "quote_role": "finding",
                            "qualifiers_match": {"intervention_match": "exact"},
                            "relation_to_claim": "direct_support",
                            "design": "animal",
                            "n_total": 32,
                            "comparison": "between_groups",
                            "effect_class": "large",
                        }
                    ],
                },
                {"id": "c2", "evidence": []},
            ],
            "alternatives": {
                "p1": {
                    "id": "p1",
                    "evidence": [
                        {
                            "source": "PubMed",
                            "record_id": "PMID:12",
                            "lab_or_cohort": "PMID:12",
                            "quote": "Repeated experimenter handling increases rotarod performance in mice.",
                            "quote_role": "finding",
                            "qualifiers_match": {"intervention_match": "exact"},
                            "design": "animal",
                            "n_total": 48,
                            "comparison": "between_groups",
                            "effect_class": "medium",
                        }
                    ],
                }
            },
            "implementation_readiness": {
                "resource_tier": "2_animal",
                "overall_evidence_status": "confirmed_in_context",
                "component_checks": [
                    {
                        "component": "delivery_or_intervention",
                        "target_system": "aged C57BL/6 mice treadmill protocol",
                        "evidence_status": "confirmed_in_context",
                        "evidence_pmid": "",
                        "evidence_quote": "comparing structured treadmill training versus sedentary cage control for 12 weeks",
                        "notes": "Standard rodent treadmill protocol.",
                    },
                    {
                        "component": "population_or_model",
                        "target_system": "aged C57BL/6 mice",
                        "evidence_status": "confirmed_in_context",
                        "evidence_pmid": "",
                        "evidence_quote": "n=40 aged C57BL/6 mice",
                        "notes": "Standard aged mouse strain.",
                    },
                    {
                        "component": "measurement_or_assay",
                        "target_system": "rotarod latency",
                        "evidence_status": "confirmed_in_context",
                        "evidence_pmid": "",
                        "evidence_quote": "primary outcome is rotarod latency",
                        "notes": "Standard motor coordination assay.",
                    },
                ],
            },
            "indicators": {"endpoint_clinical": "biomarker", "trend_pubmed": 0.1, "ai_role": "none"},
            "paper_outcomes": [],
        },
    ]


def build_kit(out_zip: Path, cutoff: str) -> dict:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    pkg_root = ROOT / "hyparena"
    cfg_root = ROOT / "configs"

    included: list[str] = []
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        def _writestr(arcname: str, text: str) -> None:
            zf.writestr(arcname, text.encode("utf-8"))
            included.append(arcname)

        def _writefile(src: Path, arcname: str) -> None:
            zf.write(src, arcname)
            included.append(arcname)

        _writestr("README.md", _readme_md(cutoff))
        _writefile(ROOT / "docs" / "method" / "manual.md", "manual.md")
        _writefile(ROOT / "docs" / "method" / "changelog-v4.0.md", "changelog-v4.0.md")
        _writefile(ROOT / "docs" / "method" / "dossier-instructions-draft.md", "dossier-instructions-draft.md")
        _writestr("requirements.txt", REQUIREMENTS_TXT)
        _writestr("calculate.py", CALCULATE_PY)
        _writestr("make_report.py", MAKE_REPORT_PY)
        _writestr("example_cases.json", json.dumps(_example_cases(), ensure_ascii=False, indent=2) + "\n")

        for cname in CONFIG_FILES:
            src = cfg_root / cname
            if src.exists():
                _writefile(src, f"configs/{cname}")

        for path in sorted(pkg_root.rglob("*")):
            if path.is_dir():
                continue
            if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            rel = path.relative_to(ROOT).as_posix()
            _writefile(path, rel)

    sha256 = hashlib.sha256(out_zip.read_bytes()).hexdigest()
    return {
        "zip_path": str(out_zip),
        "n_files": len(included),
        "size_bytes": out_zip.stat().st_size,
        "sha256": sha256,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path, help="Output .zip path")
    ap.add_argument("--cutoff", default="2026-11-27", help="Default YYYY-MM-DD cutoff shown in README and examples")
    args = ap.parse_args()
    info = build_kit(args.out, args.cutoff)
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

# Реестр скриптов (2026-11-12; спецификации — в [`specs/README.md`](../specs/README.md))

Спецификация (`specs/*.yaml`) — определения проверки, записанные до расчёта, и результат в конце. Скрипт (`scripts/*.py`) —
её расчёт. Данные — в приватном `longevity-kg`, их реестр — `longevity-kg/DATA.md`. Статусы как там: **актуальный**
(читается текущим методом v3.10, бенчмарком или планом в работе), **история** (на ней стоит число в мануале или решение;
не меняется), **заменено** (метод v1/v2; оставлено как запись решений).

## Спецификации

Реестр спецификаций (65, по папкам этапов, со статусом и строкой о каждой) перенесён в [`specs/README.md`](../specs/README.md).

## Скрипты (100)

| Группа | Скрипты | Статус |
|---|---|---|
| Текущий конвейер и данные | `benchmark_run`, `prospective`, `hypothesis_sources_ctgov`, `*_outcomes` (ctgov, isrctn, drks, anzctr, ntr, umin), `ctgov_flags`, `ctgov_recompute`, `hypothesis_db`, `profile_variants`, `profile_report`, `evolution_check`, `v34_check` (общие функции, его импортируют 35 модулей), `reread_v11` (импортируют 13), `parse_chatgpt_hypotheses`, `validation_table` | актуальный |
| Бенчмарки и пакеты Argon | `bench_reading`, `bench_card`, `bench_card_v2`, `bench_search`, `search_misses`, `calibration_leak`, `link_ontology_check`, `relabel_compare`, `pack19_card`, `pack20_relabel`, `hydrogen_card_pack`, `pack16_reading`, `pack17_card`, `pack18_search`, `pack5`–`pack13_*` (сборка и анализ), `two_step_reading`, `reading_recall` | `bench_*`, `pack16`–`pack18` — актуальный; остальные — история |
| Проверки метода v3.x | `record_weight_check`, `reread_analysis`, `empty_slots`, `i_cap_check`, `i_recalibration`, `judge_alternatives`, `propose_v2`, `link_scoring_check`, `meta_certainty`, `claim_results`, `fulltext_reread`, `test_model`, `test_model_fixcheck`, `reader_model`, `reader_v12`, `split_reader`, `pilot_crosslink`, `llm_consensus`, `experiment_forecast`, `chain_layers`, `protocol_review`, `graph_r2`, `sources_experiment`, `sources_compare`, `argon_check`, `ablation`, `ceiling`, `error_analysis`, `estimand_check`, `trend_genetics_check`, `ohf_probe`, `normalizer_v8_check`, `extraction_gold_v3`, `retrieval_eval`, `style_check`, `paraphrase_check`, `repeat_l18_l19`, `verifier_agreement`, `blind_check`, `pairwise_calibration`, `naive_baseline`, `drugage_pool`, `extraction_compare`, `fresh_outcomes`, `calibration` | история (у части данные удалены — помечено в шапке) |
| Проверки агрегации и метода v1 | `aspid_calibration`, `aspid_sensitivity`, `clean_backtest`, `benchmark_v1`, `normalizer_acceptance`, `trace_page` | история |

### Удалено 2026-11-12

`short_ids_seed`, `normalizer_prompt_check`, `normalizer_prompt_check2`, `check_annotations`, `extraction_pool`,
`extraction_fixes_eval`, `extraction_status_impact`, `itp_label_permutation`, `diagnostics_calibration`, `null_calibration`,
`llm_catalog_check`, `rule_experiments` и их тесты (12 скриптов, 5 тестов); вернуть — из истории git.

Оставлены: `aspid_calibration`, `aspid_sensitivity` (проверки агрегации ASPID, которая действует; тест —
доказательство в `specs/whole-system/validation-criteria.yaml`), `trace_page`, `clean_backtest`, `benchmark_v1`, `normalizer_acceptance`.

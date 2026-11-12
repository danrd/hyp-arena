# Реестр спецификаций и скриптов (2026-11-12)

Спецификация (`specs/*.yaml`) — определения проверки, записанные до расчёта, и результат в конце. Скрипт (`scripts/*.py`) —
её расчёт. Данные — в приватном `longevity-kg`, их реестр — `longevity-kg/DATA.md`. Статусы как там: **актуальный**
(читается текущим методом v3.9, бенчмарком или планом в работе), **история** (на ней стоит число в мануале или решение;
не меняется), **заменено** (метод v1/v2; оставлено как запись решений).

## Спецификации (60)

| Группа | Спецификации | Статус |
|---|---|---|
| Планы и бенчмарки в работе | `benchmark-reading-2026-11-12`, `known-facts-test-2026-11-09`, `mechanism-chain-comparison-2026-11-11`, `paper-skeleton-2026-11-09`, `generation-2026-11-09`, `directed-evolution-2026-11-09`, `hypothesis-db-2026-11-09` (база собрана 2026-11-12, оценки и сайт — нет) | актуальный |
| Предрегистрация (закреплено хешем) | `prospective-2026-11-06`, `prospective-llm-consensus-2026-11-07`, `prospective-pilot-2026-11-06` | актуальный, не меняется |
| Метки исходов (эталон этапов 9 и 11) | `ctgov-outcomes-2026-10-30`, `ctgov-outcomes-2023-2026`, `isrctn-outcomes-2026-10-31`, `drks-`, `anzctr-`, `ntr-`, `umin-outcomes-2026-11-01`, `benchmark-v2`, `calibration-step3-2026-11-02`, `calibration-v3-2026-11-05`, `calibration-v3-fresh-2026-11-06`, `clean-2024-12-31`, `validation-criteria` | актуальный (источник меток) |
| Проверки метода v3.x, принятые или отклонённые | `record-weight-2026-11-08`, `empty-slots-2026-11-09`, `informativeness-check-2026-11-08`, `novelty-check-2026-11-08`, `balance-check-2026-11-08`, `intervention-class-2026-11-11`, `meta-and-nulls-2026-11-09`, `llm-consensus-2026-11-07`, `v34-frontier-2026-11-07`, `v38-candidates-2026-11-10`, `link-scoring-2026-11-08`, `v32-independence-fold-2026-11-06`, `v33-2026-11-06`, `error-analysis-2026-11-06`, `estimand-2026-11-06`, `trend-genetics-2026-11-06`, `experiment-forecast-2026-11-07`, `evolution-v3-pilot-2026-11-06` | история |
| Чтение и источники | `reading-gold-2026-11-08`, `reader-model-2026-11-08`, `reader-v12-2026-11-08`, `abstract-overstates-2026-11-09`, `sources-argon-2026-11-09`, `sources-experiment-2026-11-07`, `test-model-2026-11-09`, `argon-layers-2026-11-08`, `argon-comparison-2026-11-07` | история |
| Карточка и извлечение | `normalizer-v8-2026-11-05`, `extraction-gold-v3-2026-11-04`, `-v3b-`, `-v8-`, `extraction-gold-v9-2026-11-05` | история |
| Метод v1/v2 | `benchmark-v1`, `evolution-1`, `itp-backtest-2010`, `negatives-2026-10-29`, `normalizer-acceptance-2026-10-30` | заменено |

Спецификации не удаляются: это запись того, что и почему было решено (как предрегистрация).

## Скрипты (100)

| Группа | Скрипты | Статус |
|---|---|---|
| Текущий конвейер и данные | `benchmark_run`, `prospective`, `hypothesis_sources_ctgov`, `*_outcomes` (ctgov, isrctn, drks, anzctr, ntr, umin), `ctgov_flags`, `ctgov_recompute`, `hypothesis_db`, `profile_variants`, `profile_report`, `evolution_check`, `v34_check` (общие функции, его импортируют 35 модулей), `reread_v11` (импортируют 13), `parse_chatgpt_hypotheses`, `validation_table` | актуальный |
| Бенчмарки и пакеты Argon | `pack16_reading`, `pack5`–`pack13_*` (сборка и анализ), `two_step_reading`, `reading_recall` | `pack16` — актуальный; остальные — история |
| Проверки метода v3.x | `record_weight_check`, `reread_analysis`, `empty_slots`, `i_cap_check`, `i_recalibration`, `judge_alternatives`, `propose_v2`, `link_scoring_check`, `meta_certainty`, `claim_results`, `fulltext_reread`, `test_model`, `test_model_fixcheck`, `reader_model`, `reader_v12`, `split_reader`, `pilot_crosslink`, `llm_consensus`, `experiment_forecast`, `chain_layers`, `protocol_review`, `graph_r2`, `sources_experiment`, `sources_compare`, `argon_check`, `ablation`, `ceiling`, `error_analysis`, `estimand_check`, `trend_genetics_check`, `ohf_probe`, `normalizer_v8_check`, `extraction_gold_v3`, `retrieval_eval`, `style_check`, `paraphrase_check`, `repeat_l18_l19`, `verifier_agreement`, `blind_check`, `pairwise_calibration`, `naive_baseline`, `drugage_pool`, `extraction_compare`, `fresh_outcomes`, `calibration` | история (у части данные удалены — помечено в шапке) |
| Метод v1/v2, без спецификации | `aspid_calibration`, `aspid_sensitivity`, `diagnostics_calibration`, `null_calibration`, `itp_label_permutation`, `clean_backtest`, `benchmark_v1`, `normalizer_acceptance`, `normalizer_prompt_check`, `normalizer_prompt_check2`, `check_annotations`, `extraction_pool`, `extraction_fixes_eval`, `extraction_status_impact`, `llm_catalog_check`, `short_ids_seed`, `trace_page`, `rule_experiments` | кандидаты на удаление (раздел ниже) |

### Кандидаты на удаление (на решение пользователя)

| Скрипт | Почему | Что ещё убрать |
|---|---|---|
| `short_ids_seed` | одноразовый посев номеров, заменён `hypothesis_db` | — |
| `normalizer_prompt_check`, `normalizer_prompt_check2` | сравнение промптов нормализатора v5 и v6 (сейчас v11) | их тесты |
| `check_annotations`, `extraction_pool`, `extraction_fixes_eval`, `extraction_status_impact` | проверка извлечения L1.17 метода v1 (DrugAge-аннотации) | тесты, если есть |
| `itp_label_permutation` | перестановочный тест бэктеста ITP-2010 (метод v1) | тест |
| `aspid_calibration`, `aspid_sensitivity`, `diagnostics_calibration`, `null_calibration` | симуляции агрегации и предупреждений метода v1 | тесты |
| `llm_catalog_check` | проверка каталога моделей без описания | — |
| `rule_experiments` | правила метода v2, данные удалены | — |

Оставить: `trace_page` (страница пошагового прохода по сохранённому прогону — пригодится для проходов вроде H49),
`clean_backtest`, `benchmark_v1`, `normalizer_acceptance` (на них стоят спецификации `clean-2024-12-31`, `benchmark-v1`,
`normalizer-acceptance`).

# Scripts

Calculations behind the checks in [`specs/`](../specs/README.md) and the benchmark runs. Run from the repository root as modules,
e.g. `python -m scripts.search.bench_search score`. Folders follow the stages of the system, as in `specs/` (`whole_system`
here is `whole-system` there: a Python package name cannot contain a hyphen). Data are in the private `longevity-kg`.
A script of a finished check stays: its spec names it as the calculation of its result. Paid scripts need `ALLOW_PAID=1`.

## [`common/`](common/) — Shared functions imported by many scripts (a library, not checks)

| Script | What it does |
|---|---|
| [`ablation`](common/ablation.py) | Ablation on the calibration (free, no model calls): which parts of the method carry the signal against trial outcomes and which are dead weight (user request 2026-11-07). |
| [`ceiling`](common/ceiling.py) | Ceiling analysis of the trial-outcome label (free, no model calls): do features of the trial's design, read from the ClinicalTrials.gov record, order positive and null trials better than P? If they do and P adds little to them, a low ... |
| [`reread_v11`](common/reread_v11.py) | The declared chain claims read again with verify_claim/v11 on the same papers (specs/scoring/record-weight-2026-11-08.yaml, reread_v11). Paid (DeepSeek V4.1 Flash through CometAPI). |
| [`v34_check`](common/v34_check.py) | Method v3.4 check on the saved runs, no model calls (specs/scoring/v34-frontier-2026-11-07.yaml): P v3.4 vs v3.3 on the calibration (tied AUC, exploration only), and the admission rule (separation, /Spearman rho/ < 0.7) for the new ... |

## [`data/`](data/) — Collecting and labelling data: trial outcomes by registry, hypothesis sources and database, the DrugAge pool, the leakage check

| Script | What it does |
|---|---|
| [`anzctr_outcomes`](data/anzctr_outcomes.py) | Outcome labels for ANZCTR hypotheses (specs/data/anzctr-outcomes-2026-11-01.yaml), from record pages saved by the user (MHTML). |
| [`calibration_leak`](data/calibration_leak.py) | Leak check of the calibration texts (74 trials with known outcomes). Free, no model call. |
| [`ctgov_flags`](data/ctgov_flags.py) | Flag candidates for ClinicalTrials.gov trials whose registry text may have been edited after the result (specs/data/ctgov-outcomes-2026-10-30.yaml: flags, flag_rules). |
| [`ctgov_outcomes`](data/ctgov_outcomes.py) | Outcome labels for the ClinicalTrials.gov hypotheses (specs/data/ctgov-outcomes-2026-10-30.yaml). |
| [`ctgov_recompute`](data/ctgov_recompute.py) | Tests computed from posted group values for ClinicalTrials.gov trials labelled not_reported (specs/data/ctgov-outcomes-2026-10-30.yaml: recompute_rules). |
| [`drks_outcomes`](data/drks_outcomes.py) | Outcome labels for DRKS hypotheses (specs/data/drks-outcomes-2026-11-01.yaml). |
| [`drugage_pool`](data/drugage_pool.py) | A free calibration pool from DrugAge: compounds with different depth of evidence at a date T, no labels, no model calls. |
| [`fresh_outcomes`](data/fresh_outcomes.py) | Outcome labels for the fresh calibration sample by hand-run Argon (Gemini deep research; user decision 2026-11-05), checked by code and spot-checked by Claude. |
| [`hypothesis_db`](data/hypothesis_db.py) | The hypothesis database (specs/data/hypothesis-db-2026-11-09.yaml): one row per hypothesis or version, from every source we hold, with a stable id, the short id, the text, the date it was written, the cut-off of its scoring, the outcome ... |
| [`hypothesis_sources_ctgov`](data/hypothesis_sources_ctgov.py) | Dated, human-written hypotheses from ClinicalTrials.gov: trials on aging itself, with the registered text copied verbatim and the sources of the later outcome located (no labels here; labelling is a separate, recorded step). |
| [`isrctn_outcomes`](data/isrctn_outcomes.py) | Outcome labels for ISRCTN hypotheses (specs/data/isrctn-outcomes-2026-10-31.yaml). |
| [`ntr_outcomes`](data/ntr_outcomes.py) | Outcome labels for NTR hypotheses (specs/data/ntr-outcomes-2026-11-01.yaml). |
| [`parse_chatgpt_hypotheses`](data/parse_chatgpt_hypotheses.py) | Parse a markdown dump of the ChatGPT hypothesis dialogue into structured JSON. |
| [`umin_outcomes`](data/umin_outcomes.py) | Outcome labels for UMIN-CTR hypotheses (specs/data/umin-outcomes-2026-11-01.yaml). |

## [`card/`](card/) — Stage: the hypothesis card

| Script | What it does |
|---|---|
| [`bench_card`](card/bench_card.py) | Card benchmark (specs/card/benchmark-card-2026-11-12.yaml) on Argon pack 17: 60 texts, the card gold. |
| [`bench_card_v2`](card/bench_card_v2.py) | Card benchmark against the gold under the link definitions of docs/system/card.md (card_gold_v2): Argon packs 19 (30 texts not from a registry) and 20 (the 60 texts of pack 17 labelled again). specs/card/benchmark-card-2026-11-12.yaml. |
| [`link_ontology_check`](card/link_ontology_check.py) | Can an ontology set the link type better than the model? A free check on Argon pack 17 (PubMed E-utilities only). |
| [`merge_steps`](card/merge_steps.py) | Free: the evidence balance with every step before the outcome as one place (by the weakest step with data, or by the mean), against the current places (specs/card/merge-steps-2026-11-14.yaml). Same references as ... |
| [`normalizer_acceptance`](card/normalizer_acceptance.py) | L1.18: can a cheaper normalizer replace Gemini 3.5 Flash with hidden reasoning (specs/card/normalizer-acceptance-2026-10-30.yaml)? |
| [`normalizer_v8_check`](card/normalizer_v8_check.py) | normalize_card/v8 on the 30 calibration texts, cards only (no verification), against the v7 cards of the v3 calibration. Criterion fixed before the call: specs/card/normalizer-v8-2026-11-05.yaml. |
| [`paraphrase_check`](card/paraphrase_check.py) | L1.8: invariance of the card, the statuses and the places to paraphrasing of the hypothesis text. |
| [`repeat_l18_l19`](card/repeat_l18_l19.py) | L1.8b and L1.9b: the repeat of the paraphrase and style checks after the normalizer fixes (canonical qualifiers, abbreviations, organism as the object, route words, Greek letters; prompt v6), on 15 regimens not used in L1.8, L1.9 or the ... |
| [`style_check`](card/style_check.py) | L1.9: invariance of the places to the style of the hypothesis text, next to the Elo baseline (L0). |

## [`search/`](search/) — Stage: literature search

| Script | What it does |
|---|---|
| [`bench_search`](search/bench_search.py) | Search benchmark (specs/search/benchmark-search-2026-11-12.yaml) on Argon pack 18: 30 calibration trials. Free, no model call. |
| [`graph_r2`](search/graph_r2.py) | Argon's graph on the v3.6 rules: R2 and the evidence balance, ours vs graph vs union (specs/search/sources-experiment-2026-11-07.yaml, graph_v36_2026_11_08). Free. |
| [`mesh_search_check`](search/mesh_search_check.py) | Do MeSH synonyms and shorter queries find more of the search gold? Free (PubMed E-utilities only), on Argon pack 18. |
| [`retrieval_eval`](search/retrieval_eval.py) | How well does the verifier's literature search find what it should? (calibration, 2026-11-02) |
| [`search_budget_check`](search/search_budget_check.py) | Free experiment, part 3: how to share the reading budget of a hypothesis over its searches (plan docs/plans/search-2026-11-14.md; rule in specs/search/benchmark-search-2026-11-12.yaml, free_experiments_2026_11_14). |
| [`search_expand_check`](search/search_expand_check.py) | Free experiments, part 2: candidates from links between papers, ordered by word match (plan docs/plans/search-2026-11-14.md, options Г1 and Г2; rule in specs/search/benchmark-search-2026-11-12.yaml, free_experiments_2026_11_14). PubMed ... |
| [`search_filter_check`](search/search_filter_check.py) | Paid experiment: a cheap LLM as the relevance filter before reading (plan docs/plans/search-2026-11-14.md, option Б4; rule in specs/search/benchmark-search-2026-11-12.yaml, filter_experiment_2026_11_14). |
| [`search_misses`](search/search_misses.py) | Where are the gold papers of the search benchmark lost? (Argon pack 18, saved searches v10.) Free: PubMed E-utilities only. |
| [`search_rerank_check`](search/search_rerank_check.py) | Free experiments on choosing the 20 papers per claim (plan docs/plans/search-2026-11-14.md, step 2; the admission rule is in specs/search/benchmark-search-2026-11-12.yaml, free_experiments_2026_11_14). PubMed only, no model call. |
| [`search_simple_check`](search/search_simple_check.py) | Do plain code-built queries (PubMed's automatic term mapping, no field tags) find the search gold the model-written queries miss? Free (E-utilities only), on Argon pack 18. |
| [`sources_compare`](search/sources_compare.py) | Compare arms of the sources experiment (specs/search/sources-experiment-2026-11-07.yaml) on the 15 units, free: old abstracts (v9, saved calibration runs), arm A (v10 + exact-population query), arm B (full texts, when run), Argon's graph. |
| [`sources_experiment`](search/sources_experiment.py) | Sources experiment (specs/search/sources-experiment-2026-11-07.yaml): the same 15 calibration trials read with abstracts (arm A, exact-population query, configs/v3-flash-n11.yaml) and with PMC full texts where allowed (arm B, ... |

## [`reading/`](reading/) — Stage: reading papers and extracting records

| Script | What it does |
|---|---|
| [`bench_reading`](reading/bench_reading.py) | Reading benchmark (specs/reading/benchmark-reading-2026-11-12.yaml) on Argon pack 16: 20 links, 400 link-abstract pairs. |
| [`blind_check`](reading/blind_check.py) | Paired check of name dependence of the verifier: the same saved prompt with and without the compound's names. |
| [`claim_results`](reading/claim_results.py) | Claim vs results table (specs/reading/abstract-overstates-2026-11-09.yaml, claim_vs_results): one narrow question per 'for' RCT record on the outcome link with an open paper, from the Results sections and tables; a 'no' or ... |
| [`extraction_compare`](reading/extraction_compare.py) | Extraction against the DrugAge gold, at the level of cells (compound, species, sex) with a direction. |
| [`extraction_gold_v3`](reading/extraction_gold_v3.py) | Method v3 extraction against hand-made gold, with the v2 verifier (verify_claim/v5) on the same inputs for comparison. |
| [`fulltext_reread`](reading/fulltext_reread.py) | Full-text re-read of 'for' RCT records on the outcome link (specs/reading/abstract-overstates-2026-11-09.yaml, fulltext_reread). |
| [`meta_certainty`](reading/meta_certainty.py) | Certainty-aware weight of meta-analysis records (specs/reading/meta-and-nulls-2026-11-09.yaml, meta_certainty). |
| [`pilot_crosslink`](reading/pilot_crosslink.py) | Pilot: cross-link reading in small batches, then the split reader (specs/scoring/balance-check-2026-11-08.yaml, pilot_crosslink). |
| [`reader_model`](reading/reader_model.py) | Is a stronger reader model worth it? (specs/reading/reader-model-2026-11-08.yaml). Paid for `run`. |
| [`reader_v12`](reading/reader_v12.py) | Reader v12 pilot (specs/reading/reader-v12-2026-11-08.yaml): a relevance filter before reading and an answer for every paper. |
| [`reading_recall`](reading/reading_recall.py) | Reading recall diagnostics (docs/plans/reading-recall-2026-11-08.md, steps 1-2, free). |
| [`reread_analysis`](reading/reread_analysis.py) | Measures of the v11 re-read (specs/scoring/record-weight-2026-11-08.yaml, reread_v11). Free. |
| [`split_reader`](reading/split_reader.py) | Split reader (specs/reading/reader-model-2026-11-08.yaml, split_reader): DeepSeek's records, Gemini re-labels only the intervention match and the contradicted qualifiers, one short call per claim. Paid for `run`. |
| [`test_model`](reading/test_model.py) | The test model of a hypothesis (specs/reading/test-model-2026-11-09.yaml): arms, prediction matrix, decision criteria, rigour. |
| [`test_model_fixcheck`](reading/test_model_fixcheck.py) | Free check (user request 2026-11-09): does a code rule fix the matrix's systematic error, a proposed competitor of the same kind as a checklist row (natural course, expectation, practice ...) not inheriting that row's "held equal"? ... |
| [`two_step_reading`](reading/two_step_reading.py) | Two-step reading on the pack-9 links (specs/reading/reading-gold-2026-11-08.yaml, two_step_test). Paid for `run`. |
| [`verifier_agreement`](reading/verifier_agreement.py) | L1.10: agreement of verifier families on the status of the main claim (Cohen's kappa), same cards, only the verifier changes. |

## [`scoring/`](scoring/) — Stage: scoring links, the evidence balance and the ranking profiles

| Script | What it does |
|---|---|
| [`aspid_calibration`](scoring/aspid_calibration.py) | ASPID aggregation calibration by simulation (check if p_topk is calibrated). |
| [`aspid_sensitivity`](scoring/aspid_sensitivity.py) | Sensitivity of the ASPID ranking to the weights of a profile, on random pools of hypotheses (Kendall tau between orders) |
| [`chain_layers`](scoring/chain_layers.py) | Argon's layers 3-4 on the calibration, free (user decision 2026-11-08): the weakest link as a hard gate and convergence of independent kinds of evidence; plus "surprise" as the inverse of the models' probability (for reference). |
| [`empty_slots`](scoring/empty_slots.py) | Free: v3.6 balance with empty slots counted (as now) vs skipped (specs/scoring/empty-slots-2026-11-09.yaml). |
| [`error_analysis`](scoring/error_analysis.py) | Error analysis of P on the calibration samples (steps 1-5), no model calls (specs/scoring/error-analysis-2026-11-06.yaml). |
| [`estimand_check`](scoring/estimand_check.py) | Estimand check (specs/scoring/estimand-2026-11-06.yaml): five ICH E9(R1) attributes from the registry texts by two model families, then the four admission conditions for an indicator. |
| [`experiment_forecast`](scoring/experiment_forecast.py) | Forecast from the experiment (specs/scoring/experiment-forecast-2026-11-07.yaml): protocol from ClinicalTrials.gov, expected effect from the records of the outcome slot, power, room for bias -> P(positive). Free; exploration on the ... |
| [`link_scoring_check`](scoring/link_scoring_check.py) | specs/scoring/link-scoring-2026-11-08.yaml: A (chain state), B (null weighted by power), G (silent links) on the calibration (AUC) and on calibration + prospective (admission rule). Free. |
| [`ohf_probe`](scoring/ohf_probe.py) | Two OHF ideas checked on the saved records of the calibration (steps 1-5), no model calls (2026-11-06; method-v3.md section 13): four-axis indirectness (system, intervention, endpoint, comparison) in place of the context and comparison ... |
| [`profile_report`](scoring/profile_report.py) | Which indicators separate the hypotheses of a saved run, how far the profiles pull the order apart, and which indicators move together. Reads the site bundles (runs/site/*.json); no model calls, nothing is changed. |
| [`profile_variants`](scoring/profile_variants.py) | Alternative tier orders of the ASPID profiles (user requests 2026-11-09: frontier sets; W higher in funding). Free. |
| [`protocol_review`](scoring/protocol_review.py) | Protocol review of each calibration trial by two model families (Argon's layers 1-2, user decision 2026-11-08): endpoint signal-to-noise, add-on ceiling, time window, power realism, population enrichment, delivery, room for bias. A ... |
| [`record_weight_check`](scoring/record_weight_check.py) | specs/scoring/record-weight-2026-11-08.yaml: the record weight and the fold of for / against, step by step. Free (no model calls; PubMed E-utilities for years and abstracts, cached in data/cache/pubmed). |
| [`trend_genetics_check`](scoring/trend_genetics_check.py) | The check of specs/scoring/trend-genetics-2026-11-06.yaml on saved runs (no model calls). |

## [`alternatives/`](alternatives/) — Stage: competing explanations and informativeness

| Script | What it does |
|---|---|
| [`i_cap_check`](alternatives/i_cap_check.py) | Sensitivity of I to its cap (specs/alternatives/informativeness-check-2026-11-08.yaml, cap_check). Free. |
| [`i_recalibration`](alternatives/i_recalibration.py) | I on the calibration with the d judged from the registry text vs the proposer's d (specs/alternatives/informativeness-check-2026-11-08.yaml, item 3 of 2026-11-08). Free. Exploration: the 73 units built the method; an AUC moves by about ... |
| [`judge_alternatives`](alternatives/judge_alternatives.py) | d of the proposed alternatives judged from the registry text (specs/alternatives/informativeness-check-2026-11-08.yaml, fix_d). Paid (DeepSeek V4.1 Flash through CometAPI), one call per trial. |
| [`propose_v2`](alternatives/propose_v2.py) | Alternatives proposed with the registry text and a checklist of competitor kinds (propose_alternatives/v2), d judged by judge_alternatives/v2 (specs/alternatives/informativeness-check-2026-11-08.yaml, fix_d step2). Paid; holdout trials ... |

## [`evolution/`](evolution/) — Stage: improvement of hypotheses

| Script | What it does |
|---|---|
| [`evolution_check`](evolution/evolution_check.py) | Free: the evolution rules (manual section 11) and the hypothesis / experiment decomposition on saved evolution pairs. |

## [`whole_system/`](whole_system/) — Checks of the whole system against outcomes: calibration, benchmark runs, frozen forecasts, ITP backtests, baselines

| Script | What it does |
|---|---|
| [`benchmark_run`](whole_system/benchmark_run.py) | Benchmark v2 (specs/data/benchmark-v2.yaml), the free part: hypothesis texts, the formal baseline and a dry run with the cost. |
| [`benchmark_v1`](whole_system/benchmark_v1.py) | Frozen unit list of the benchmark (specs/data/benchmark-v2.yaml; v1 kept in data/benchmark/v1_units.json): human registry hypotheses with decisive outcomes. |
| [`calibration`](whole_system/calibration.py) | Calibration of method v2 on registry hypotheses outside the benchmark, in growing steps (user decision 2026-11-02). |
| [`clean_backtest`](whole_system/clean_backtest.py) | L3.3 and L3.9 on the clean ITP + CITP pool (T = 2024-12-31) without an LLM verifier: no model reads the pool. |
| [`llm_consensus`](whole_system/llm_consensus.py) | Baseline from the Eternal Search Omega preprint (user decision 2026-11-07): ask models "will it be confirmed experimentally?" for each calibration trial and compare with P. Paid (about 146 calls on two cheap families). |
| [`naive_baseline`](whole_system/naive_baseline.py) | L3.9: our rank against the naive "approved first" order (path_to_human only) on the ITP backtest, paired over compounds. |
| [`pairwise_calibration`](whole_system/pairwise_calibration.py) | L3.11: calibration of the pairwise probabilities P(A>B) of the profile evidence_first against the ITP 2010 labels. |
| [`prospective`](whole_system/prospective.py) | The prospective pool: ongoing trials scored before their outcomes exist (the start of the living arena, method-v3.md section 10). |
| [`trace_page`](whole_system/trace_page.py) | Build a step-by-step page (Russian) from a recorded run: every graph node in order, what it does, which code and prompt template run, every model and search call with its full prompt and reply, and what the node produced. |
| [`validation_table`](whole_system/validation_table.py) | Render specs/whole-system/validation-criteria.yaml into docs/validation-criteria.md (summary, one table per level, the criteria below). |

## [`argon/`](argon/) — Tasks for the outside reader (Argon): building packs 5-22 and analysing the answers

| Script | What it does |
|---|---|
| [`argon_check`](argon/argon_check.py) | Re-check of Argon's pack 3 (specs/search/sources-experiment-2026-11-07.yaml, arm C and the gold labels), free: quotes verbatim (abstract, or the PMC full text where PMC allows it), publication date before the cut-off, PMID exists; then ... |
| [`hydrogen_card_pack`](argon/hydrogen_card_pack.py) | Card task for an outside strong model (Hydrogen): the 22 texts where normalize_card/v15 on the working model made substantive errors (specs/card/benchmark-card-2026-11-12.yaml, full_run_v15_2026_11_14.weak_texts). Free, no model call. |
| [`pack10_analysis`](argon/pack10_analysis.py) | Analysis of Argon pack 10 (specs/search/sources-argon-2026-11-09.yaml). Free. |
| [`pack10_sources`](argon/pack10_sources.py) | Argon pack 10: abstract vs PMC full text vs knowledge graph (specs/search/sources-argon-2026-11-09.yaml). Free (PubMed / PMC metadata). |
| [`pack11_analysis`](argon/pack11_analysis.py) | Analysis of Argon pack 11 (specs/reading/abstract-overstates-2026-11-09.yaml). Free. |
| [`pack11_overstates`](argon/pack11_overstates.py) | Argon pack 11: does the abstract overstate the trial? (specs/reading/abstract-overstates-2026-11-09.yaml). Free (PubMed / Europe PMC). |
| [`pack12_analysis`](argon/pack12_analysis.py) | Analysis of Argon pack 12 (specs/reading/meta-and-nulls-2026-11-09.yaml). Free. |
| [`pack12_meta_nulls`](argon/pack12_meta_nulls.py) | Argon pack 12: meta-analyses read as for, RCTs read as against (specs/reading/meta-and-nulls-2026-11-09.yaml). Free. |
| [`pack13_claim_results`](argon/pack13_claim_results.py) | Argon pack 13 (user choice 2026-11-09, variant V): every record the claim-vs-results check changed or proposed to change. Private output only (longevity-kg), it quotes papers. |
| [`pack16_reading`](argon/pack16_reading.py) | Argon pack 16: one full reading gold per (link, paper) for the reading benchmark (specs/reading/benchmark-reading-2026-11-12.yaml). Free, deterministic (hash order, no model call). Writes the task in two parts and the hidden key to the ... |
| [`pack17_card`](argon/pack17_card.py) | Argon pack 17: the card gold (docs/benchmarks/README.md, stage 2; specs/card/mechanism-chain-comparison-2026-11-11.yaml texts). Free, deterministic (hash order), no model call. Writes the task in two parts and the hidden key to the ... |
| [`pack18_search`](argon/pack18_search.py) | Argon pack 18: the search gold (docs/benchmarks/README.md, stages 3 and 6). Free, deterministic, no model call. |
| [`pack19_card`](argon/pack19_card.py) | Argon pack 19: the card gold on texts that are not registry trials (docs/benchmarks/README.md, stage 2). Free, deterministic (hash order), no model call. Writes the task and the hidden key to the private repository. |
| [`pack20_relabel`](argon/pack20_relabel.py) | Argon pack 20: the 60 texts of pack 17 labelled again under the link-type definitions of docs/system/card.md (card_gold_v2, the same instructions as pack 19 plus the rules for registry texts). Free, deterministic, no model call. |
| [`pack21_pmid_fix`](argon/pack21_pmid_fix.py) | Argon pack 21: the right PMIDs for the papers of the search gold (pack 18) whose number points to another paper. Free, deterministic, no model call. |
| [`pack22_alternatives`](argon/pack22_alternatives.py) | Argon pack 22: the gold for stage 7 (competing explanations): for the 30 calibration trials of the search gold (pack 18), the main alternative explanations of the result the trial would show, what the stated design does to each, and the ... |
| [`pack5_analysis`](argon/pack5_analysis.py) | Analysis of Argon pack 5 (specs/scoring/record-weight-2026-11-08.yaml references.R4_pairs_argon). Free. |
| [`pack6_analysis`](argon/pack6_analysis.py) | Analysis of Argon pack 6 (specs/alternatives/informativeness-check-2026-11-08.yaml, measures fixed before sending). Free. |
| [`pack6_informativeness`](argon/pack6_informativeness.py) | Argon pack 6: a second reader of I (specs/alternatives/informativeness-check-2026-11-08.yaml). Free (no model calls). |
| [`pack7_analysis`](argon/pack7_analysis.py) | Analysis of Argon pack 7 (specs/novelty/novelty-check-2026-11-08.yaml, measures fixed before sending). Free (PubMed for PMIDs). |
| [`pack7_novelty`](argon/pack7_novelty.py) | Argon pack 7: a second reader of novelty N (specs/novelty/novelty-check-2026-11-08.yaml). Free (no model calls). |
| [`pack8_analysis`](argon/pack8_analysis.py) | Analysis of Argon pack 8 (specs/scoring/balance-check-2026-11-08.yaml, measures fixed before sending). Free (PubMed for PMIDs). |
| [`pack8_balance`](argon/pack8_balance.py) | Argon pack 8: a second reader of the evidence balance, link by link (specs/scoring/balance-check-2026-11-08.yaml). Free. |
| [`pack9_analysis`](argon/pack9_analysis.py) | Analysis of Argon pack 9 (specs/reading/reading-gold-2026-11-08.yaml, measures fixed before sending). Free. |
| [`pack9_reading`](argon/pack9_reading.py) | Argon pack 9: a gold of findings per (link, paper) for the reader's recall (specs/reading/reading-gold-2026-11-08.yaml). Free. |
| [`relabel_compare`](argon/relabel_compare.py) | Pack 20 against pack 17 (the same 60 texts, the outside reader under the old and the new link definitions) and our saved v13 cards against the new gold. Free, no call. |

## Removed 2026-11-12

`short_ids_seed`, `normalizer_prompt_check`, `normalizer_prompt_check2`, `check_annotations`, `extraction_pool`,
`extraction_fixes_eval`, `extraction_status_impact`, `itp_label_permutation`, `diagnostics_calibration`, `null_calibration`,
`llm_catalog_check`, `rule_experiments` and their tests (12 scripts, 5 tests); restore them from the git history.

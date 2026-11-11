# Commands

The command-level reference moved out of the README. Tests: `pip install -e . pytest && python -m pytest tests/`. Runs that
call models need `ALLOW_PAID=1` and an API key (see [`configs/`](../configs/); [`configs/v2-direct.yaml`](../configs/v2-direct.yaml)
skips families whose key is not set; the aggregators CometAPI and OpenRouter are supported).

## Benchmark v2 (registry hypotheses)

Protocol: [`benchmark.md`](benchmark.md), [`specs/benchmark-v2.yaml`](../specs/benchmark-v2.yaml). Texts are private
(`$KG_DIR/hypothesis_sources`); the public repository holds ids, labels, dates and flags only.

- Unit list: `python -m scripts.benchmark_v1` (writes `data/benchmark/v2_units.json` and prints its sha256)
- Hypothesis texts from registry fields: `python -m scripts.benchmark_run texts`
- Registry header fields and the formal baseline: `python -m scripts.benchmark_run features`, then `... baseline`
- Dry run with the fake LLM (calls and input tokens per role): `python -m scripts.benchmark_run dry`
- Pilot on trials outside the benchmark (paid): `ALLOW_PAID=1 python -m scripts.benchmark_run pilot`
- Registry labelling, per source: `scripts/ctgov_outcomes.py`, `isrctn_outcomes.py`, `drks_outcomes.py`, `ntr_outcomes.py`,
  `umin_outcomes.py`, `anzctr_outcomes.py` (paid steps behind `ALLOW_PAID=1`); flags and recomputed tests: `scripts/ctgov_flags.py`,
  `scripts/ctgov_recompute.py`

## Calibration and method v3

- Calibration on trials outside the benchmark, in steps: `scripts/calibration.py` (pick, units, run, score, score-v3; usage in its docstring)
- Retrieval evaluation (gold from CT.gov background references and DrugAge): `scripts/retrieval_eval.py`
- Offline rule experiments on the saved calibration records: `python -m scripts.rule_experiments`
- Method v3: `configs/v3-flash.yaml` (`method: v3`), with normalize_card/v10 `configs/v3-flash-n10.yaml`; rules in
  `hyparena/card/rules_v3.py` (variants v3, v3.1), `rules_v32.py` (v3.2, applied to saved records), levels in `v3_levels.py`;
  ASPID over the axes `hyparena/card/aspid_v3.py` with `configs/profiles_v3.yaml`
- Rule variants on saved records (no calls): `python -m scripts.calibration compare-v32 --steps 4,5`; scores by v3 / v3.1:
  `score-v3 --steps ... --variant v3.1`, sensitivity `--no-stance-as-support`
- Fresh sample (outcomes labelled by hand-run Argon from our tasks, checked by code and Claude): `scripts/fresh_outcomes.py`
  (task, check, expand, expand_registries, units)
- Prospective pool: `python -m scripts.prospective pool | pick --n 60 | run | estimand | score | freeze` (paid steps behind
  `ALLOW_PAID=1`; scores frozen with a SHA-256 in `specs/prospective-<date>.yaml`); `score` writes method v3.4 to `scores_<n>_v34.json`
- Method v3.4 check (free; P v3.4 vs v3.3, admission rule for novelty, leverage, density): `python -m scripts.v34_check`
- Error analysis (free): `python -m scripts.error_analysis [--v33]`; ablation: `python -m scripts.ablation`; ceiling of the label: `python -m scripts.ceiling`
- Evolution: `python -m hyparena.card.evolve_v3 --top 10 --profile evidence --dry` (choice, free); `--mode tune` (доработка) or `--mode free --writer FAMILY` (свободная эволюция), paid behind `ALLOW_PAID=1`
- Analysis report of a hypothesis (by code, no calls): `python -m hyparena.analyze RUN.json [--unit ID]`; reports on private
  hypotheses go to `$KG_DIR/hypothesis_sources/analysis/`
- Indicator checks (four conditions, criteria in `specs/`): extraction gold `scripts/extraction_gold_v3.py`, normaliser
  `scripts/normalizer_v8_check.py`, OHF ideas `scripts/ohf_probe.py`, estimands `python -m scripts.estimand_check run | score`,
  trend and genetic support `python -m scripts.trend_genetics_check`

## Historical backtests (ITP, CITP)

- ITP pool as of a date, hidden labels: `python -m hyparena.backtest build-itp --as-of 2010-12-31`, then
  `python -m hyparena.live run --import-file data/backtest/itp_2010-12-31.json --as-of 2010-12-31 --out runs/r.json`
  (add `--mode coscientist` for the baseline), then `python -m hyparena.backtest evaluate --labels data/backtest/itp_2010-12-31_labels.json --result runs/r.json`.
  The pool is derived from DrugAge (HAGR, CC BY 3.0; cite de Magalhães et al. 2024) and PubMed dates.
- Method v2 on a pool: `python -m hyparena.backtest v2 --pool ... --out runs/x.json`
- Post-2022 ITP and CITP outcomes from the batch papers: `python -m hyparena.outcomes build --as-of T`; metrics:
  `python -m hyparena.outcomes metrics --labels ... --v2 runs/x.json`; model eligibility by cutoff: `python -m hyparena.outcomes models --as-of T`
- Clean pool without an LLM verifier: `scripts/clean_backtest.py` (usage in its docstring)

## Other tests and tools

- Negative-sampling test: `python -m hyparena.negatives` ([`negative-sampling.md`](archive/negative-sampling.md))
- Retraction check: `python -m hyparena.tools.retractions download` (Retraction Watch CSV, ~67 MB, kept out of git)
- Tournament simulation prototype: `python -m hyparena.sim` (takes a few minutes)
- Graph skeleton with a fake LLM (no real calls): `python -m hyparena.demo`
- Demonstration interface (Gradio, in Russian): `pip install -e ".[demo]" && python -m hyparena.app`, see [`demo.md`](archive/demo.md)
- Live runs on real models (free OpenRouter models by default): `python -m hyparena.live smoke` and `python -m hyparena.live run`
  (`--checkpoint runs/state.sqlite` makes a run resumable with `--resume --thread <id>`; `--criteria`, `--card`,
  `--search europepmc|none`, `--as-of YYYY-MM-DD`). Models: [`configs/models.yaml`](../configs/models.yaml); cheap paid models for
  small tests: [`configs/paid-test.yaml`](../configs/paid-test.yaml).
- Example data: [`data/chatgpt_hypotheses.json`](../data/chatgpt_hypotheses.json), 27 hypotheses in Russian parsed from a ChatGPT
  dialogue with `scripts/parse_chatgpt_hypotheses.py`; load them into a run with `--import-file`.

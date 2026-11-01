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

- Negative-sampling test: `python -m hyparena.negatives` ([`negative-sampling.md`](negative-sampling.md))
- Retraction check: `python -m hyparena.tools.retractions download` (Retraction Watch CSV, ~67 MB, kept out of git)
- Tournament simulation prototype: `python -m hyparena.sim` (takes a few minutes)
- Graph skeleton with a fake LLM (no real calls): `python -m hyparena.demo`
- Demonstration interface (Gradio, in Russian): `pip install -e ".[demo]" && python -m hyparena.app`, see [`demo.md`](demo.md)
- Live runs on real models (free OpenRouter models by default): `python -m hyparena.live smoke` and `python -m hyparena.live run`
  (`--checkpoint runs/state.sqlite` makes a run resumable with `--resume --thread <id>`; `--criteria`, `--card`,
  `--search europepmc|none`, `--as-of YYYY-MM-DD`). Models: [`configs/models.yaml`](../configs/models.yaml); cheap paid models for
  small tests: [`configs/paid-test.yaml`](../configs/paid-test.yaml).
- Example data: [`data/chatgpt_hypotheses.json`](../data/chatgpt_hypotheses.json), 27 hypotheses in Russian parsed from a ChatGPT
  dialogue with `scripts/parse_chatgpt_hypotheses.py`; load them into a run with `--import-file`.

# hyp-arena

A research prototype for ranking hypotheses about ageing and healthy lifespan. Each hypothesis is turned into a
structured card of claims; the claims are checked against PubMed abstracts and DrugAge with verbatim quotes; rules
compute indicators from the checked evidence (effect level, robustness, path to humans, novelty and others); the
hypotheses are then ranked under explicit preference profiles with SMAA, which gives each one an interval and a
probability of being in the top k rather than a single score. A Co-Scientist-style tournament (Elo) is included as
a baseline.

Status: work in progress. The method is evaluated on worked examples, a negative-sampling test and a historical
backtest against the Interventions Testing Program; the samples are small and the results are reported with their
intervals in [`docs/rules-method.md`](docs/rules-method.md). The rankings are research output, not medical advice.

Quick start: `pip install -e . pytest && python -m pytest tests/`. Runs that call models need `ALLOW_PAID=1` and an
API key of OpenAI, Anthropic, Google Gemini, DeepSeek, xAI or Mistral ([`configs/v2-direct.yaml`](configs/v2-direct.yaml):
families whose key is not set are skipped), or of the aggregators CometAPI or OpenRouter (see [`configs/`](configs/)). The site
<https://danrd.github.io/hyp-arena/site/> shows an example run (Elo tournament next to the ranking under preference
profiles, the verified card of each hypothesis), lets you download the results as JSON or CSV, opens your own runs,
and explains how to rank your own hypotheses with your own API key (source: [`docs/site/index.html`](docs/site/index.html)).

Data sources: PubMed (NCBI E-utilities), DrugAge (HAGR, CC BY 3.0; de Magalhães et al. 2024), ChEMBL, ChEBI (OLS4),
ClinicalTrials.gov. Code under the MIT licence ([`LICENSE`](LICENSE)).

## Documentation and tools

- Approach: [`docs/approach.md`](docs/approach.md)
- **Method v2 (2026-10-19): verified card → rule-based indicators → aggregation under preference profiles**: [`docs/rules-method.md`](docs/rules-method.md); specifications in [`docs/spec/`](docs/spec/); tests: `pip install pytest && python -m pytest tests/`
- **Bio Arena (bioarena.ru)**, an open LLM-judged tournament of ageing hypotheses: how it works, our export of its 985 hypotheses and 6,822 matches, and how it relates to our method: [`docs/bioarena.md`](docs/bioarena.md); data in `data/bioarena/`
- Architecture (LangGraph multi-agent design, now the baseline and ablation harness; section 0 maps the method v2 decisions to the code): [`docs/architecture.md`](docs/architecture.md)
- Criteria, card schema and models are configuration: [`configs/criteria.yaml`](configs/criteria.yaml), [`configs/card.yaml`](configs/card.yaml) (draft), [`configs/models.yaml`](configs/models.yaml)
- Comparison protocol (our ranking vs Co-Scientist-style baselines, the 2025 Elo version and the 2026 TrueSkill + UCB version; ablation ladder, budgets, statistics): [`docs/comparison.md`](docs/comparison.md)
- Aggregation of criteria without numeric weights (order of importance, МРСП): [`hyparena/aggregate.py`](hyparena/aggregate.py); lines of work and where the code stands: [`docs/approach.md`](docs/approach.md), section 8a
- Negative-sampling test (a confirmed DrugAge finding among nine plausible false statements; hit@1, MRR, per kind of negative): [`docs/negative-sampling.md`](docs/negative-sampling.md), `python -m hyparena.negatives`
- How Co-Scientist works (hypothesis format, judges, criteria): [`docs/co-scientist-reference.md`](docs/co-scientist-reference.md)
- Example data: [`data/chatgpt_hypotheses.json`](data/chatgpt_hypotheses.json), 27 hypotheses in Russian parsed from a ChatGPT dialogue (writer: openai / gpt-6-astra-wm) with `scripts/parse_chatgpt_hypotheses.py`; load them into a run with `--import-file`
- Backtest (ITP pool as of a date, hidden labels): `python -m hyparena.backtest build-itp --as-of 2010-12-31`, then `python -m hyparena.live run --import-file data/backtest/itp_2010-12-31.json --as-of 2010-12-31 --out runs/r.json` (add `--mode coscientist` for the baseline), then `python -m hyparena.backtest evaluate --labels data/backtest/itp_2010-12-31_labels.json --result runs/r.json`. The pool is derived from DrugAge (HAGR, CC BY 3.0; cite de Magalhães et al. 2024) and PubMed dates. Method v2 on a pool: `python -m hyparena.backtest v2 --pool ... --out runs/x.json`; post-2022 ITP and CITP outcomes from the batch papers: `python -m hyparena.outcomes build --as-of T`, metrics with `python -m hyparena.outcomes metrics --labels ... --v2 runs/x.json`, model eligibility by cutoff with `python -m hyparena.outcomes models --as-of T`.
- Retraction check: `python -m hyparena.tools.retractions download` (Retraction Watch CSV, ~67 MB, kept out of git)
- Tournament simulation prototype: `pip install -e . && python -m hyparena.sim` (takes a few minutes)
- Graph skeleton with a fake LLM (no real calls): `python -m hyparena.demo`
- Demonstration interface (Gradio, in Russian: paste or generate a few hypotheses, get a ranking; a saved example opens instantly): `pip install -e ".[demo]" && python -m hyparena.app`, see [`docs/demo.md`](docs/demo.md)
- Live checks on real models (free OpenRouter models by default; paid ones need `ALLOW_PAID=1`): `python -m hyparena.live smoke` and `python -m hyparena.live run` (add `--checkpoint runs/state.sqlite` to make a run resumable with `--resume --thread <id>`; `--criteria`, `--card`, `--search europepmc|none`, `--as-of YYYY-MM-DD` for backtests). Models are set in [`configs/models.yaml`](configs/models.yaml); cheap paid models for small tests are in [`configs/paid-test.yaml`](configs/paid-test.yaml) (`--config configs/paid-test.yaml`, needs `COMET_API_KEY` and `ALLOW_PAID=1`).

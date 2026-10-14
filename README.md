# hyp-arena

An approach to ranking thousands of scientific hypotheses (biology, ageing) by promise and feasibility, based on ideas from Google's Co-Scientist.

- Approach: [`docs/approach.md`](docs/approach.md)
- Architecture (LangGraph multi-agent design): [`docs/architecture.md`](docs/architecture.md)
- Criteria, card schema and models are configuration: [`configs/criteria.yaml`](configs/criteria.yaml), [`configs/card.yaml`](configs/card.yaml) (draft), [`configs/models.yaml`](configs/models.yaml)
- How Co-Scientist works (hypothesis format, judges, criteria): [`docs/co-scientist-reference.md`](docs/co-scientist-reference.md)
- Example data: [`data/chatgpt_hypotheses.json`](data/chatgpt_hypotheses.json), 27 hypotheses in Russian parsed from a ChatGPT dialogue (writer: openai / gpt-6-astra-wm) with `scripts/parse_chatgpt_hypotheses.py`; load them into a run with `--import-file`
- Backtest (ITP pool as of a date, hidden labels): `python -m hyparena.backtest build-itp --as-of 2010-12-31`, then `python -m hyparena.live run --import-file data/backtest/itp_2010-12-31.json --as-of 2010-12-31 --out runs/r.json` (add `--mode coscientist` for the baseline), then `python -m hyparena.backtest evaluate --labels data/backtest/itp_2010-12-31_labels.json --result runs/r.json`. The pool is derived from DrugAge (HAGR, CC BY 3.0; cite de Magalhães et al. 2024) and PubMed dates.
- Retraction check: `python -m hyparena.tools.retractions download` (Retraction Watch CSV, ~67 MB, kept out of git)
- Tournament simulation prototype: `pip install -e . && python -m hyparena.sim` (takes a few minutes)
- Graph skeleton with a fake LLM (no real calls): `python -m hyparena.demo`
- Live checks on real models (free OpenRouter models by default; paid ones need `ALLOW_PAID=1`): `python -m hyparena.live smoke` and `python -m hyparena.live run` (add `--checkpoint runs/state.sqlite` to make a run resumable with `--resume --thread <id>`; `--criteria`, `--card`, `--search europepmc|none`, `--as-of YYYY-MM-DD` for backtests). Models are set in [`configs/models.yaml`](configs/models.yaml); cheap paid models for small tests are in [`configs/paid-test.yaml`](configs/paid-test.yaml) (`--config configs/paid-test.yaml`, needs `COMET_API_KEY` and `ALLOW_PAID=1`).

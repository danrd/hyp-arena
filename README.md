# hyp-arena

An approach to ranking thousands of scientific hypotheses (biology, ageing) by promise and feasibility, based on ideas from Google's Co-Scientist.

- Approach: [`docs/approach.md`](docs/approach.md)
- Architecture (LangGraph multi-agent design): [`docs/architecture.md`](docs/architecture.md)
- How Co-Scientist works (hypothesis format, judges, criteria): [`docs/co-scientist-reference.md`](docs/co-scientist-reference.md)
- Example data: [`data/chatgpt_hypotheses.json`](data/chatgpt_hypotheses.json), 27 hypotheses in Russian parsed from a ChatGPT dialogue with `scripts/parse_chatgpt_hypotheses.py`
- Tournament simulation prototype: `pip install -e . && python -m hyparena.sim` (takes a few minutes)
- Graph skeleton with a fake LLM (no real calls): `python -m hyparena.demo`
- Live checks on real models (free OpenRouter models by default; paid ones need `ALLOW_PAID=1`): `python -m hyparena.live smoke` and `python -m hyparena.live run`. Models are set in [`configs/models.yaml`](configs/models.yaml); cheap paid models for small tests are in [`configs/paid-test.yaml`](configs/paid-test.yaml) (`--config configs/paid-test.yaml`, needs `COMET_API_KEY` and `ALLOW_PAID=1`).

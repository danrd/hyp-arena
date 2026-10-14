# hyp-arena

An approach to ranking thousands of scientific hypotheses (biology, ageing) by promise and feasibility, based on ideas from Google's Co-Scientist.

- Approach: [`docs/approach.md`](docs/approach.md)
- Architecture (LangGraph multi-agent design): [`docs/architecture.md`](docs/architecture.md)
- How Co-Scientist works (hypothesis format, judges, criteria): [`docs/co-scientist-reference.md`](docs/co-scientist-reference.md)
- Example data: [`data/chatgpt_hypotheses.json`](data/chatgpt_hypotheses.json), 27 hypotheses in Russian parsed from a ChatGPT dialogue with `scripts/parse_chatgpt_hypotheses.py`
- Tournament simulation prototype: `pip install -e . && python -m hyparena.sim` (takes a few minutes)
- Graph skeleton with a fake LLM (no real calls): `python -m hyparena.demo`

# Task for Jules in hyp-arena: a catalogue of LLMs with release dates and knowledge cutoffs

Task for hyp-arena: build `data/models/llm_catalog.yaml`, a catalogue of large language models with their release dates and their knowledge (training data) cutoffs, every value with its source. It is used to decide which models may judge a backtest pool as of a date T (a model may only if its knowledge cutoff is not after T), so a wrong or invented date is worse than a missing one.

Scope:
- Every LLM released from 2023-01-01 to today by these developers, including dated snapshots and preview versions served through an API: OpenAI, Anthropic, Google (Gemini, Gemma), Meta (Llama), Mistral, DeepSeek, Alibaba (Qwen), Zhipu (GLM), Moonshot (Kimi), xAI (Grok), Microsoft (Phi), Cohere, AI21, Amazon (Nova), NVIDIA (Nemotron), MiniMax, Xiaomi (MiMo), 01.AI, Baidu (ERNIE), Tencent (Hunyuan), ByteDance (Seed / Doubao).
- Plus every model listed by the aggregators we use: CometAPI (`https://api.cometapi.com/api/models`) and OpenRouter (`https://openrouter.ai/api/v1/models`), whatever the developer.

One entry per model (YAML list under `models:`), fields:
- `id`: the developer's model name; `aliases`: other names and snapshot ids; `developer`; `family`; `open_weights`: true/false
- `released`: first public availability (YYYY-MM-DD, or YYYY-MM if only the month is known); `released_kind`: preview | ga | weights; `released_source`: URL
- `cutoff`: the knowledge cutoff exactly as the developer states it (YYYY-MM-DD, YYYY-MM or YYYY); `cutoff_quote`: the sentence that states it, copied verbatim (at most 200 characters); `cutoff_source`: URL of an official page (model card, API documentation, release notes, technical report)
- `cutoff_conflicts`: other official statements that disagree, each with quote and URL
- `aggregator_ids`: `{cometapi: ..., openrouter: ...}` where listed
- `notes`, `checked_on`: the date you read the sources

Rules:
- Knowledge cutoff only from official sources of the developer. If the developer does not state it, write `cutoff: null` and in `notes` "not stated by the developer", listing the pages you checked. Never infer a cutoff from the release date, from benchmarks, from asking the model, or from third-party blogs.
- Release dates may come from official announcements, documentation changelogs or the aggregators' `created` fields; say which in `released_source`.
- Do not copy values from one model to another (a snapshot can have another cutoff than its family).
- Write a script `scripts/llm_catalog_check.py` that validates the file (required fields, date formats, a source URL for every non-null date, quote present when cutoff is set) and a test `tests/test_llm_catalog.py` that runs it. Run `python -m pytest tests/test_llm_catalog.py` until it passes.
- Do not edit `configs/model_cutoffs.yaml` or other existing files: the catalogue is reviewed before it is used.

Second, smaller part: look in the Internet Archive (Wayback Machine, `https://web.archive.org/cdx/search/cdx?url=nia.nih.gov/research/dab/interventions-testing-program-itp*`) for archived pages of the NIA Interventions Testing Program that list compounds proposed or in testing, with any rationale given for choosing them. Write `data/models/itp_archive_findings.md` (despite the folder name, keep it there for now): which archived URLs and dates exist, whether they give a rationale per compound, and for which compounds; no copying of whole pages, short excerpts with links only.

Pull request: title "LLM catalogue: release dates and knowledge cutoffs with sources; ITP archive findings". In the description: how many models, how many with a stated cutoff, which developers state none, and anything you could not check.

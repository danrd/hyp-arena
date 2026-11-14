# hyparena

The code of the method. Folders follow the stages of the system, as in [`specs/`](../specs/README.md) and
[`scripts/`](../scripts/README.md). Prompts are in [`prompts/`](prompts/) (one folder per role, versions inside); report
templates in [`templates/`](templates/). Run modules from the repository root, e.g. `python -m hyparena.pipeline`.

## Top level — The pipeline that joins the stages (pipeline, rank), short ids of hypotheses, specs fixed before a run (prespec)

| Module | What it does |
|---|---|
| [`pipeline`](pipeline.py) | The method end to end: texts → card → search and reading → records → the rules of the config's method (`method: v3` in the working configs; v2 kept for old runs) → indicators → aggregation under each preference profilerchive/docs/rules-method.md). |
| [`prespec`](prespec.py) | Specifications fixed before the data are read (test plan A4). |
| [`rank`](rank.py) | Ranking of verified cards (our method): admission → gate → known-result check → rule-based indicators → aggregation under each preference profile → candidates robust across profiles. No LLM here: ... |
| [`short_ids`](short_ids.py) | Short ids of hypotheses (H01, H02, ...; versions H49д, H49д2), kept in the hypothesis database. |

## `card/` — Stage: the hypothesis card (model, normaliser, entities, contexts, canonical wording)

| Module | What it does |
|---|---|
| [`canonical`](card/canonical.py) | Canonical wording of what a normalizer writes: dose, age at the start (also ranges), intervention names without a route word, the organism as the object of a lifespan or healthspan claim. |
| [`contexts`](card/contexts.py) | Context flags for evidence records: disease models, progeroid and short-lived strains, special diets (configs/disease_models.yaml). Which strain a study used is in the text; what the strain means ... |
| [`entities`](card/entities.py) | Identifiers for the compounds of a card (card spec 4: "id optional at normalization; resolved later"). |
| [`lifespan`](card/lifespan.py) | `late_start` (card spec 8a; tables and lookup rule: Data_Sources 19): the age at the start of the intervention as a fraction of the median lifespan of controls, capped at 1. An exact age ("600 ... |
| [`llm`](card/llm.py) | One structured LLM call: render a template, parse the JSON, validate it, and ask again with the reasons when it does not pass (at most `rounds` attempts). Every attempt is appended to `log` when ... |
| [`models`](card/models.py) | Hypothesis card v1 (MVP) as Pydantic models: the single source of truth for the format, exported to JSON Schema (docs/spec/hypothesis-card-spec.md; field names follow it). |
| [`normalizer`](card/normalizer.py) | Normalizer: hypothesis text → declared card (card spec section 9). The LLM parses; code validates the schema, the closed vocabulary, exactly one outcome claim and that every source_span is ... |

## `search/` — Stage: literature search

| Module | What it does |
|---|---|
| [`search`](search/search.py) | Literature search of one claim with model-written queries (calibration 2026-11-02, configs with `search: model`). |
| [`search_rank`](search/search_rank.py) | Ordering of search candidates before reading, by code: BM25 of the query terms against title and abstract (the search benchmark, specs/search/benchmark-search-2026-11-12.yaml, ... |
| [`search_vocab`](search/search_vocab.py) | Vocabulary guard for model-written PubMed queries (calibration, 2026-11-02). |

## `reading/` — Stage: reading papers into evidence records

| Module | What it does |
|---|---|
| [`effect_class`](reading/effect_class.py) | Effect class by code from the verbatim effect phrase (user decision 2026-11-04, option A; archive/docs/spec/method-v3.md, section 2). |
| [`review_kind`](reading/review_kind.py) | Review kind and meta-analysis certainty by code (user decision 2026-11-11, H49 walkthrough stage 5). |
| [`sources`](reading/sources.py) | Curated evidence for lifespan claims from DrugAge (HAGR, CC BY 3.0): deterministic, no LLM. One record per publication and species for the claim's compound: supporting if any row of that paper ... |
| [`verifier`](reading/verifier.py) | Verifier: claim → evidence records (card spec section 7). Sources: DrugAge (curated, deterministic, lifespan claims) and PubMed abstracts (an LLM extracts records). Code then checks that every ... |

## `scoring/` — Stage: record weights, link strength, rules of v3, indicators, ASPID

| Module | What it does |
|---|---|
| [`aggregate`](scoring/aggregate.py) | Aggregation of per-criterion ratings without explicit weights. Based on the method of randomized aggregated indicators (МРСП, part of Hovanov's АСПИД methodology; international analogue: SMAA) and ... |
| [`aspid`](scoring/aspid.py) | Aggregation of rule-based indicators under an ordinal importance order: МРСП / АСПИД (Hovanov) in its SMAA-2 form (Lahdelma, Salminen; implementation after Tervonen, Lahdelma 2007). Implements ... |
| [`aspid_v3`](scoring/aspid_v3.py) | ASPID over the axes of method v3 (configs/profiles_v3.yaml; method-v3.md section 13). |
| [`expert`](scoring/expert.py) | Expert layer (card spec 7a; Aggregation_Spec 6a): expert decisions kept apart from the declared and verified layers. What each decision does: - with a `source` on a claim (or a rejected ... |
| [`indicators`](scoring/indicators.py) | Rule-based indicators for the aggregation (card spec, section 8a), computed from the declared card and its verified layer. Every value is a fact derived from the card or `None` (unknown); unknowns ... |
| [`rules`](scoring/rules.py) | Deterministic rules over the card (no LLM): validation, admission, claim statuses, the evidence profile and the known-result check (card spec sections 4a, 7, 8, 10). |
| [`rules_v3`](scoring/rules_v3.py) | Method v3 rules (archive/docs/spec/method-v3.md, sections 3-6 and 9): record weight on ordinal scales, link strength, the gate, plausibility P, scope W, informativeness I, promise V = P x W x I, ... |
| [`rules_v32`](scoring/rules_v32.py) | Method v3.2 (method-v3.md section 13, user decision 2026-11-06): continuous scores, so that hypotheses whose links are all "weak" are still told apart. Applied offline to saved records; runs ... |
| [`trend_genetics`](scoring/trend_genetics.py) | Two indicators from public data, no model calls (specs/scoring/trend-genetics-2026-11-06.yaml): |
| [`v3_extra`](scoring/v3_extra.py) | Additional indicators of a v3 result, computed by code from the card and the saved records (no model calls), for the lower tiers of the ASPID profiles over the v3 axes ... |
| [`v3_levels`](scoring/v3_levels.py) | Ordinal scales of method v3 and their weights (archive/docs/spec/method-v3.md, section 3). |

## `alternatives/` — Stage: competing explanations and informativeness of the experiment

| Module | What it does |
|---|---|
| [`alternatives`](alternatives/alternatives.py) | Alternative explanations in the verified layer (card spec 8c). Added by code after the verifier: |
| [`alternatives_d`](alternatives/alternatives_d.py) | The d of the proposed alternatives judged from the registry text (judge_alternatives/v2; user decision 2026-11-08, specs/alternatives/informativeness-check-2026-11-08.yaml): it replaces the ... |
| [`alternatives_v3`](alternatives/alternatives_v3.py) | Method v3: alternatives proposed by a model (archive/docs/spec/method-v3.md, section 4). |
| [`informativeness`](alternatives/informativeness.py) | Informativeness (card spec 8c): how many of the open alternative explanations the decisive experiment of the hypothesis, as written, discriminates (0 to 4). One call per hypothesis; code keeps an ... |

## `novelty/` — Stage: novelty and proximity

| Module | What it does |
|---|---|
| [`novelty_v34`](novelty/novelty_v34.py) | Novelty, leverage and the drift flag of method v3.4 (specs/scoring/v34-frontier-2026-11-07.yaml), computed by code from the saved records, no model calls. |
| [`proximity`](novelty/proximity.py) | Typed proximity from the card (card spec 8b): similarity over resolved entity identifiers in PICO and over claims in the closed relation vocabulary; the output is a relation type, not one number. |

## `evolution/` — Stage: improvement list and evolution

| Module | What it does |
|---|---|
| [`evolution_rules`](evolution/evolution_rules.py) | Code checks of the rules every improved version keeps (method-v3-manual.md section 11, user decision 2026-11-09), and the decomposition of a version's score change into the hypothesis part and the ... |
| [`evolve`](evolution/evolve.py) | Evidence-guided evolution of hypotheses over method v2. Parents are the top-ranked hypotheses of a saved v2 result; a child is a refinement driven by what the verification found (narrow to a ... |
| [`evolve_v3`](evolution/evolve_v3.py) | Evolution under method v3.3: apply the improvement list of chosen hypotheses (hyparena/evolution/improvements.py) and score the result the same way (user decision 2026-11-06: the analysis names ... |
| [`improvements`](evolution/improvements.py) | The list of improvements of one hypothesis, computed by code from its v3.3 analysis (user decision 2026-11-06: the analysis names the places to improve explicitly; evolution applies them, nothing ... |

## `whole_system/` — Checks of the whole system: ITP backtests, negatives, snapshot, leakage probe

| Module | What it does |
|---|---|
| [`backtest`](whole_system/backtest.py) | Backtest harness: build a labelled pool "as of date T" and evaluate a run against hidden labels. |
| [`leakage`](whole_system/leakage.py) | Leakage probe: which backtest items does each judge model already know the outcome of? |
| [`negatives`](whole_system/negatives.py) | Negative-sampling test: does the ranking put a confirmed finding above plausible false ones? |
| [`outcomes`](whole_system/outcomes.py) | Backtest pools from curated program outcomes (Working_Notes A2, decided 2026-10-20). |
| [`snapshot`](whole_system/snapshot.py) | Golden snapshot of the ITP-2010 backtest: one row per tested regimen (status of the main claim, place under the `evidence_first` profile, expectation, P(top-k)), written from the site bundle that ... |

## `reports/` — Reports, the site, diagnostics, resources of a run

| Module | What it does |
|---|---|
| [`analyze`](reports/analyze.py) | Analysis report of a hypothesis under method v3: why it got its scores and what would raise them. |
| [`diagnostics`](reports/diagnostics.py) | Diagnostics of a pool of ranked hypotheses: how many indicators vary, how many pairs a profile orders. |
| [`diversity`](reports/diversity.py) | A second kind of result next to the ranking: the top without relatives (2026-10-23). |
| [`report_html`](reports/report_html.py) | Pool report as one HTML page: a snapshot of the site for one pool (user decision 2026-11-06). |
| [`report_v2`](reports/report_v2.py) | Pool report, second layout (user decision 2026-11-07, reshaped 2026-11-11: five tabs — ranking, hypothesis cards (text only), evaluation of hypotheses (numbers), how it works, help in two levels; ... |
| [`site`](reports/site.py) | Data bundle and build for the site (docs/site/index.html). |
| [`usage`](reports/usage.py) | Resources of a run: calls, tokens, seconds and USD per stage of the method, computed by code from the call log. |

## `coscientist/` — The Co-Scientist-style baseline of method v2: graph, agents, tournament, ratings, ablation ladder, demo

| Module | What it does |
|---|---|
| [`context`](coscientist/context.py) | Run-time dependencies shared by all nodes: LLM client, tools, tracer, provenance log, config. |
| [`data`](coscientist/data.py) | Load externally produced hypotheses (the ChatGPT dataset) as graph hypotheses with known provenance. |
| [`demo`](coscientist/demo.py) | Run the graph end to end with the fake LLM (no real model calls): python -m hyparena.coscientist.demo |
| [`experiment`](coscientist/experiment.py) | Run the comparison grid: ladder steps x seeds x token budgets, one result file per run. |
| [`graph`](coscientist/graph.py) | LangGraph assembly: supervisor-driven cycles of generate -> ... -> meta_review, then a report. |
| [`ladder`](coscientist/ladder.py) | Ablation ladder from the Co-Scientist baseline (L0) to our full method (L4), one change per step. L0ts is the second baseline: the 2026 version of Co-Scientist (TrueSkill + UCB) instead of Elo. |
| [`live`](coscientist/live.py) | Live checks against real models, free tier by default. |
| [`persist`](coscientist/persist.py) | Persistent graph state (Co-Scientist's context memory): a LangGraph SQLite checkpointer. |
| [`provenance`](coscientist/provenance.py) | Append-only log of every LLM call and notable events (JSON lines). |
| [`rating`](coscientist/rating.py) | Bradley-Terry ratings per axis and adaptive pair selection (ported from sim.py). |
| [`schema`](coscientist/schema.py) | Configurable parts of the comparison: the criteria judges compare on and the hypothesis card schema. |
| [`showcase`](coscientist/showcase.py) | Demonstration run: a handful of pasted or generated hypotheses -> ranking, as one JSON-serializable result and a self-contained HTML page (Russian interface). Used by the Gradio app (hyparena/app.py). |
| [`state`](coscientist/state.py) | Graph state and the records it holds. Hypotheses and matches are append-only. |
| [`agents/`](coscientist/agents/) | the agents of the graph: generate, review, tournament, evolve, meta-review, report, supervisor |

## `llm/` — Model clients, prompts, structured replies, the fake LLM

| Module | What it does |
|---|---|
| [`anthropic_runner`](llm/anthropic_runner.py) | Claude through the official Anthropic SDK (Messages API), with the `generate(prompt) -> str` interface of llm_kit's runners. Not through an OpenAI-compatible shim: current Claude models reject ... |
| [`client`](llm/client.py) | LLM access. Every call returns a Reply that says which model actually answered. |
| [`fake`](llm/fake.py) | A deterministic stand-in LLM, enough to exercise the graph shape (no real model behind it). |
| [`gemini_native_runner`](llm/gemini_native_runner.py) | Gemini through its native `generateContent` endpoint (by default CometAPI's copy of it), with the `generate(prompt) -> str` interface of llm_kit's runners. Not through the OpenAI-compatible ... |
| [`judges`](llm/judges.py) | Judge pool and the independence rule: judges must not share a family with the text's writer. |
| [`prompts`](llm/prompts.py) | Prompt rendering from `prompts/<name>/<version>.j2` (same layout as llm_kit.PromptBuilder blocks). |
| [`providers`](llm/providers.py) | Build the LLM client and judge pool from configs/models.yaml. |
| [`structured`](llm/structured.py) | Structured replies: ask for JSON, validate it, and ask again with the reasons when it is wrong. |

## `tools/` — Data sources and connectors (PubMed, PMC, DrugAge, MeSH, ChEBI, trials, ...)

| Module | What it does |
|---|---|
| [`bioarena`](tools/bioarena.py) | Export of Bio Arena (bioarena.ru), an open tournament of hypotheses on ageing: hypotheses with their texts, moderation and evidence dossiers, the Bradley–Terry ranking snapshot, and every pairwise ... |
| [`chebi`](tools/chebi.py) | ChEBI classes of a compound for `analog_weak` in typed proximity (card spec 8b, agreed 2026-10-21): two compounds of which at least one has no ChEMBL mechanism target are weak analogs when their ... |
| [`clinicaltrials`](tools/clinicaltrials.py) | ClinicalTrials.gov API v2 connector: registered human studies (status, phase, dates, enrollment). |
| [`compounds`](tools/compounds.py) | Compound identifiers: a name → its PubChem parent compound (salts and hydrates collapse to the parent: "quercetin dihydrate" and "quercetin" are the same compound), with the preferred name, ... |
| [`drugage`](tools/drugage.py) | DrugAge (HAGR, CC BY 3.0; de Magalhães et al. 2024): all rows of the current release, with the last good download kept. |
| [`embed`](tools/embed.py) | Embedding interface plus a dependency-free hashing embedder (a stand-in for a real model). |
| [`europepmc`](tools/europepmc.py) | Europe PMC connector (REST search, no key needed). Abstract excerpts as evidence text. |
| [`http`](tools/http.py) | Shared HTTP helper for connectors: one client, retries with backoff, last error kept. |
| [`mesh`](tools/mesh.py) | MeSH descriptors for the card's entities, found by code through NCBI E-utilities (no model): an exact match of the descriptor or of one of its entry terms, else nothing (no guessing). Cached on ... |
| [`opengenes`](tools/opengenes.py) | Open Genes connector (a curated database of ageing-related genes; API without key). |
| [`pmc`](tools/pmc.py) | Full texts from the PubMed Central open-access subset (sources experiment, specs/search/sources-experiment-2026-11-07.yaml; user decision 2026-11-07: open access only, nothing that bypasses a ... |
| [`pubdates`](tools/pubdates.py) | First public date of PubMed papers (NCBI E-utilities), cached: the date cut of every run at a date T rests on it. |
| [`pubmed`](tools/pubmed.py) | PubMed via NCBI E-utilities: search (optionally as of a date) and fetch of full abstracts, which the verifier needs to check that every quote is verbatim. Cached in memory and in data/cache/pubmed ... |
| [`pubtator`](tools/pubtator.py) | PubTator3 connector: articles with normalized entities (genes, chemicals, diseases, ...). |
| [`registry`](tools/registry.py) | Build the search tool from source names, so that runs can choose connectors by configuration. |
| [`retractions`](tools/retractions.py) | Retraction check from the Retraction Watch dataset (Crossref; CSV from GitLab, ~67 MB). |
| [`search`](tools/search.py) | Literature search interface. Every connector returns Evidence records (hyparena.coscientist.state.Evidence). |
| [`trials`](tools/trials.py) | ClinicalTrials.gov (API v2): the start date of the earliest registered trial with an intervention, for `path_to_human` as of a date T (card spec 8a: a clinical-stage compound has a trial started ... |

# Architecture: a Co-Scientist-style multi-agent graph

Status: design, not implemented. The first code iteration is a skeleton with a fake LLM, no real calls and no tests for now.

This document turns the approach in [`approach.md`](approach.md) into a concrete multi-agent design built on LangGraph, reusing [`toolkit`](https://github.com/danrd/toolkit) (`llm_kit`, `agent_kit`). How the original system works is summarized in [`co-scientist-reference.md`](co-scientist-reference.md).

## 1. Principles

1. **Reproduce the Co-Scientist template first**: the same agents and the same generate, review, rank, evolve loop. Deviate only where `approach.md` already argues for it.
2. **Our deviations are few and explicit** (section 3): two rating axes, a Bradley–Terry tournament with adaptive pair selection, a judge ensemble that is independent of the generator, a normalization layer, and full provenance.
3. **Agents are plain functions** over a shared state. LangGraph provides routing and checkpointing; independent LLM calls inside a node run on a thread pool. Nodes call our LLM layer directly and do not depend on LangChain model classes.
4. **Every LLM output is attributable.** Each text, review and verdict records which model (family, exact version), prompt version and rubric version produced it.
5. **Hypotheses are append-only.** Nothing edits a hypothesis; evolution creates new ones (as in Co-Scientist).

## 2. Agent mapping

| Co-Scientist agent | Node(s) here | Main difference |
|---|---|---|
| Supervisor | `supervisor` (router) | Cycle-based instead of an asynchronous worker queue; parallelism comes from a thread pool inside a step |
| Goal parsing | `parse_goal` | Same output: preferences, attributes, constraints. Attributes are fixed to two axes, promise and feasibility, plus any goal-specific ones |
| Generation | `generate` | Free-form text, as in the paper. Search-grounded strategy uses a pluggable search tool (stubbed at first) |
| (none) | `normalize` | **New.** Extracts a structured record from the free text, flags missing fields, keeps the original text |
| Reflection | `review` | Initial, full (with search), and deep-verification reviews. Observation, simulation and recurrent reviews are later additions |
| Proximity | `proximity` | Embedding graph, clusters, deduplication |
| Ranking | `tournament` | Bradley–Terry per axis, adaptive pair selection, judge ensemble, debate for top and contested pairs |
| Evolution | `evolve` | Same strategies; creates new hypotheses with parent links |
| Meta-review | `meta_review` | Same: feedback appended to other agents' prompts, final research overview |

## 3. Deviations from Co-Scientist

| Topic | Co-Scientist | Here | Why |
|---|---|---|---|
| Ratings | One Elo (initial 1200) over configured criteria | Bradley–Terry with a standard error, **separate for promise and feasibility** | Uncertainty drives pair selection; the two axes conflict (`approach.md`, sections 1 and 5) |
| Pair selection | Similar hypotheses, newer and top-ranked first | Elimination towards top-k, a Swiss exploration share, and a proximity bias | Simulation showed +15 pp top-5% recall at the same budget |
| Judges | One model family | **Several families, none from the generator's lineage** | Correlated errors and self-preference |
| Format | Free text only | Free text **plus** a normalized record | Per-axis, explainable verdicts; deduplication |
| Verdict | One holistic "better idea" | Verdict **per axis** plus rationale, from one call | Needed for two ratings |
| Provenance | Not described | Mandatory on every artifact | Reproducibility, independence checks |

## 4. Graph

```
                         ┌────────────────────────────────────────────────────┐
                         │                    supervisor                      │
                         │  (stats, budget, stop test, picks the next step)   │
                         └───▲───────────────┬───────────────────────────▲────┘
                             │               │ conditional edges         │
   goal ─► parse_goal ───────┘               ▼                           │
                                 ┌────────── step ──────────┐            │
                                 │ generate ─► normalize     │            │
                                 │      ▼                    │            │
                                 │   review ─► proximity     │            │
                                 │      ▼                    │            │
                                 │  tournament ─► evolve     │────────────┘
                                 │      ▼                    │
                                 │  meta_review              │
                                 └───────────────────────────┘
                                             │ stop
                                             ▼
                                   report (research overview, Pareto front)
```

- **Routing.** After `parse_goal`, the `supervisor` chooses the next node through conditional edges from the current statistics (hypotheses awaiting review, tournament progress, share of new hypotheses that win matches, budget left). In the common case it runs one full cycle: generate, normalize, review, proximity, tournament, evolve, meta-review.
- **Parallelism.** Independent calls inside a node (generations, normalizations, reviews per hypothesis, matches per pair, evolutions) run on a thread pool (`Context.map`, `RunConfig.workers`). The client caps requests in flight (`concurrency`) and the request rate (`rpm`), so the pool size does not raise the load on providers. Assignments that rotate (generator, reviewer families, strategies) are fixed in order before the parallel work starts, and each match has its own random generator derived from the seed and the pair, so parallel execution does not change who judges what. A thread pool was chosen over LangGraph's `Send` fan-out because it keeps each agent a plain function and needs no extra graph nodes; `Send` remains possible later. This replaces the paper's asynchronous workers.
- **Stop test.** Token or call budget exhausted, a maximum number of cycles, or top-k stability (the top-k set barely changes over the last cycles).
- **Memory.** A LangGraph SQLite checkpointer (`hyparena/persist.py`) stores the state after every node under a thread id; a stopped run (crash, call cap, daily limit) continues from its last checkpoint (`python -m hyparena.live run --checkpoint runs/state.sqlite --resume --thread <id>`). The state models are registered with the serializer, as LangGraph's strict mode requires. What is outside the graph state (trace, call counters, rotation positions) starts afresh on resume. Provenance is additionally written to an append-only JSONL log.

## 5. State

State is one typed object (pydantic or `TypedDict`) with reducers for the parts that parallel branches write.

```
GraphState
  goal: str
  plan: PlanConfig                    # preferences, attributes, constraints
  hypotheses: dict[id, Hypothesis]    # append-only
  ratings: dict[axis, dict[id, Rating]]   # Bradley–Terry score, se, games
  matches: list[Match]                # append-only match log
  proximity: ProximityGraph           # neighbours and cluster ids
  feedback: dict[agent, str]          # meta-review text appended to prompts
  budget: Budget                      # calls, tokens, cycles used and allowed
  cycle: int
```

```
Hypothesis
  id, text                            # original free-form text, never modified
  record: NormalizedRecord | None     # claim, mechanism, prediction, experiment,
                                      #   falsification, known, assumptions, gaps[]
  provenance: Provenance              # see below
  parents: list[id]                   # for evolved hypotheses
  status: new | reviewed | rejected | active | merged
  reviews: list[Review]               # type, scores, notes, citations, provenance
  cluster: int | None

Provenance
  family, model_version, prompt_version, strategy, created_at, call_id

Match
  a, b, mode (single | debate), order, judges: list[JudgeVerdict]
  JudgeVerdict: provenance, verdict_per_axis, rationale, parse_status

Rating
  score, se, games
```

## 6. Nodes in detail

### 6.1 `parse_goal`
One LLM call turning the free-text goal into `PlanConfig`: preferences, attributes, constraints. The two axes are always present. Output is parsed with a refine loop (section 8) so a malformed reply is retried with the reason.

### 6.2 `generate`
Strategies from the paper, each with its own instructions in the prompt (`generate/v2`): literature exploration (search tool; without passages, unattributed statements must be labelled as assumptions), simulated scientific debate (one call in which the model privately runs the panel and outputs only the refined hypothesis), iterative assumptions identification (a chain of testable conditional assumptions), research expansion (directions not covered by existing hypotheses). The plan's desired attributes are part of the prompt. Output is free-form text for domain experts. Generator model rotates over the family pool so the provenance has variety; this is configurable.

### 6.3 `normalize` (new)
Extracts the structured record from the free text (claim, mechanism, prediction, experiment, falsification, known versus assumed). Missing fields are listed in `gaps`. Implemented with `agent_kit.refine.loop`: `parse` reads JSON into the record; `review` checks completeness (for example, no falsification condition) and sends the reasons back. The original text is kept and is the primary input for judges; the record and the list of missing fields are shown to judges next to it (`compare/v2`, `debate/v2`). The ChatGPT dataset (`data/chatgpt_hypotheses.json`) already has this shape.

### 6.4 `review`
Pipeline per hypothesis, as in the paper:
1. **Initial review** (no tools): correctness, quality, novelty, preliminary safety. Cheap filter; rejects obvious failures.
2. **Full review** (with search): the same criteria with retrieved literature. Novelty is judged **only** with retrieval (the paper's ablation: 6.14/10 without, 2.38/10 with).
3. **Deep verification**: decompose into assumptions and sub-assumptions, check each independently. Failures are marked fundamental or not.

**Reviewers never come from the writer's family**, also when the client falls back to another family after a failure (`avoid`), because the judges read the reviews. Observation, simulation and recurrent reviews are later additions. Every claim in a review carries a citation or the label "assumption". A grounding check (citation exists and supports the claim) can run as the `review` function of a refine loop.

### 6.5 `proximity`
Embeds hypotheses (an `Embedder` interface, stubbed), builds a neighbour graph and clusters, and merges near-duplicates above a threshold (merged ones stay in the log with `status = merged` and a pointer). Clusters are used by pair selection and by final diversification.

### 6.6 `tournament`
The core node. One round:
1. **Select pairs** from the active hypotheses: eliminate those whose upper bound is below the k-th best lower bound; pair neighbours in rating among candidates; reserve a share for a Swiss exploration round. (Planned, not implemented: a bias towards pairs in the same cluster and priority for new hypotheses.)
2. **Pick judges** for each pair with the independence rule (section 7).
3. **Judge** each pair in single-turn mode; escalate to a multi-turn debate for top-ranked pairs and for contested pairs (judges disagree, or the verdict flips when positions are swapped).
4. **Update** Bradley–Terry ratings per axis and their standard errors from the full match log.

The pair-selection logic is the one prototyped in `hyparena/sim.py`; the node reuses it behind a function interface.

### 6.7 `evolve`
Creates new hypotheses from the top of the ranking: grounding in literature, feasibility and coherence improvement, inspiration from top hypotheses, combination, simplification, out-of-the-box. A new hypothesis never replaces its parents; it has `parents` set and must win its own matches. Evolved hypotheses go through `normalize` and `review` like any other in the next cycle. Evolution is skipped in the last cycle, since its output could not be evaluated; when a run stops early (budget or a stable top), hypotheses created in the last cycle are listed in the report as `pending` instead of being dropped silently.

### 6.8 `meta_review`
Summarizes recurring problems in reviews and debate rationales into feedback strings per agent, stored in `state.feedback` and injected into the next prompts through a `feedback` block (no fine-tuning). The final research overview is written by the `report` node.

### 6.9 `supervisor`
Decides after each cycle whether to run another one or stop: maximum number of cycles, estimated token budget, or an unchanged top-k over the last two cycles. Not implemented yet: the paper's allocation of work between agents by their measured effectiveness (for example, how often evolved hypotheses reach the top).

### 6.10 `report`
Pareto front over the two axes, selection by team-set weights, near-duplicates removed using clusters, and for each shown hypothesis: the original text, the record, reviews with citations, the match history, and the full provenance. A **research overview** (the Meta-review agent's final output in Co-Scientist) is written from the shown hypotheses: research areas, first experiments, conflicts and overlaps, open risks (`research_overview/v1`). Hypotheses that were never evaluated are listed as `pending`.

## 7. Judge ensemble and independence

Rule (from `approach.md`): judges must not come from the generator's lineage.

- **Lineage mode.** Two modes, set in the run configuration. **`writer` (default, the looser one):** only the family of the model that wrote the text is excluded. **`lineage` (strict):** the writer's family plus the families of all ancestors in `parents` are excluded. The default is `writer` because evolution mixes many generators, and the strict mode can leave too few judges.
- **Eligible judges for a pair** = pool minus the excluded families of `a` minus the excluded families of `b`, under the chosen mode.
- **Unknown generator** (imported or human-written): nothing can be excluded, so use several different families and report their agreement.
- **One judge per family**; sampled with a seed recorded in the match.
- **Number of judges.** Early rounds: 1 to 2. Escalation for contested pairs: 3 or more from different families, then debate.
- **If fewer judges than requested are eligible**, the node does not silently relax the rule. With at least one eligible judge it proceeds with fewer (the match records how many judged); with none it skips the match and writes a shortfall event to the provenance log.
- **Position swap.** Order is randomized; contested pairs are rerun with swapped positions.
- **Aggregation.** Majority per axis; the disagreement itself is stored and is a signal for escalation.

## 8. LLM layer

```
LLMClient.call(role, family, model, prompt_blocks, **gen) -> Reply
Reply: text, model_id (what actually answered), tokens_in, tokens_out, seconds
```

- **Runners.** One `llm_kit` hosted runner per (family, model version), with a single model and **no fallback chain** for judges. Fallback is acceptable for non-judge roles only if the actual `model_id` is recorded. Access goes through OpenRouter or another OpenAI-compatible service; open-weight families can be self-hosted.
- **Gaps in `toolkit` (read-only for this project, to be done upstream).** `generate(prompt) -> str` does not return the model identifier or token usage. Until then a thin wrapper here estimates tokens (`ApproxTokenizer`) and records the configured model as `model_id`; the fallback case cannot be identified, which is why judges get no fallback.
- **Providers and tiers.** `configs/models.yaml` lists one model per family with a provider and a tier. **Free** models go through OpenRouter (tests); **paid** models go through CometAPI (key variable `COMET_API_KEY`, overriding the toolkit default). A paid model is refused unless the environment variable `ALLOW_PAID=1` is set, so tests cannot spend money by accident. Family keys are vendor-level (`google` covers both Gemma and Gemini, since they share a lineage).
- **Guarded client.** `GuardedClient` adds a request-rate limit, a hard cap on calls (every attempt counts), retries with backoff, and no retries on errors that cannot be fixed by retrying (400, 401, 403, 404). After the retries are spent it returns an empty reply with `error` set, and the pipeline's own validation handles it; exceeding the call cap stops the run. It also turns an empty or `None` model reply into an empty string.
- **Per-attempt deadline.** Each attempt also has a wall-clock deadline (`deadline` in the config). The HTTP client's own timeout measures silence between bytes, and a gateway that keeps the connection alive can defeat it; this was observed on CometAPI (a call that hung for more than ten minutes). A timed-out call counts as a failure and goes through the retry and fallback path.
- **Reasoning models.** On an open-ended generation prompt, reasoning models can spend the whole output budget on hidden reasoning and return an empty answer (observed with `gpt-5-nano` and `glm-5.3-flash`), while a short judging prompt works. Each model entry may override the generation settings (including `extra_body`) to limit reasoning; `configs/paid-test.yaml` holds settings that were checked on a real generation prompt. Estimated token counts exclude hidden reasoning tokens.
- **Prompts.** `llm_kit.PromptBuilder` blocks, versioned as `<name>/<version>.j2`, adapted (not copied) from the structure of the paper's prompts. Prompt and rubric versions go into the provenance.
- **Tracing.** `agent_kit.trace.Tracer` wraps every call in a span; the phase list is replaced with this project's phases (`generate`, `normalize`, `review`, `proximity`, `rank`, `debate`, `evolve`, `meta`, `other`).
- **Refine loop.** `agent_kit.refine.loop` is used for: normalization (completeness checks), judge-verdict parsing (retry on unparsable replies), and optional citation grounding. `RefineResult.attempts` are stored, because whether retries help is a measurement, not an assumption (as the module's own documentation says). `RefiningModule` is not used: it expects a module interface that `toolkit` does not define.
- **Tools.** A `SearchTool` interface (`search(query) -> list[Passage]`), stubbed first, with Europe PMC and OpenAlex implementations later.
- **Embeddings.** An `Embedder` interface, stubbed first.

## 9. Package layout

```
hyparena/
  sim.py                 # existing simulation (kept as is)
  state.py               # state, hypothesis, provenance, match, rating
  graph.py               # LangGraph assembly: nodes, edges, checkpointer
  agents/
    supervisor.py  parse_goal.py  generate.py  normalize.py  review.py
    proximity.py   tournament.py  evolve.py    meta_review.py  report.py
  llm/
    client.py            # LLMClient, Reply, runner wiring, token estimation
    judges.py            # family pool, eligibility, sampling
  rating.py              # Bradley–Terry, pair selection (from sim.py)
  tools/
    search.py            # SearchTool interface + stub
    embed.py             # Embedder interface + stub
  prompts/               # Jinja blocks, versioned
  provenance.py          # append-only JSONL log
```

Dependencies in `pyproject.toml`: `toolkit[llm-kit,llm-kit-openrouter]` (includes `agent_kit`), `langgraph`, `numpy`.

## 10. Out of scope for the first iteration

- Real LLM calls, real search, real embeddings, tests and runs (a fake `LLMClient` is enough to exercise the graph shape).
- Observation, simulation and recurrent reviews.
- Cluster bias in pair selection (clusters are computed and stored, but pairing uses ratings only).
- Multi-turn debate as separate calls: the skeleton asks for the whole panel discussion in one call and a final JSON verdict.
- `llm_kit.PromptBuilder`: prompts are rendered with Jinja2 directly from the same `<name>/<version>.j2` layout, so `PromptBuilder` can be swapped in later.
- Calibration of judges against expert labels (designed in `approach.md`, sections 7 and the judge ensemble).
- Expert-in-the-loop input (expert hypotheses and reviews, as in the paper's interface). Decision: not in the first version, and no state fields are reserved for it yet.

## 11. Decisions and open questions

Decided:
1. **Lineage strictness:** the looser `writer` mode is the default; `lineage` is available.
2. **Expert in the loop:** not in the first version.

Open:
1. **Per-axis debate.** Whether a debate should be run per axis or once for both axes (the skeleton runs once for both).
2. **Rating when axes disagree.** The Pareto front is shown, but pair selection uses a combined score; the weights live in the plan configuration.
3. **Cost caps.** The skeleton caps tokens (estimated) and cycles; the budget unit and defaults are placeholders.

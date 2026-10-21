# Architecture: a Co-Scientist-style multi-agent graph

Status (2026-10-20): implemented and tested; since the method v2 decisions (card spec, Working_Notes A3) this graph is **the baseline and ablation harness**, not the main ranking. The main mode is method v2 ([`rules-method.md`](rules-method.md), `hyparena/card/`): verified card → rule-based indicators → АСПИД per preference profile. Section 0 maps the decisions to the code; sections 1–11 describe the graph, which still runs the Co-Scientist baselines (2025, 2026) and the ladder of ablations.

## 0. Method v2 against this design (reconciled with Working_Notes A3, 2026-10-20)

| Topic | This graph (sections 1–11) | Decided (A3) | Code now |
|---|---|---|---|
| Ranking | tournament per criterion with judges, МРСП over win shares | rule-based indicators + АСПИД; tournaments only in baselines and the ablation | v2: `hyparena/card/indicators.py`, `hyparena/aspid.py`, `rank.py`; the tournament runs only in `--mode coscientist*` and the ladder L0–L4 |
| Debates | escalation for top and contested pairs, ends in a verdict | strong hypotheses only (P(top-k) ≥ 0.5); outputs are check requests, refinements, discriminating experiments, no verdict | **not yet in v2** (stage C); the verdict debates exist only in the baselines. The v2 pipeline already does the check for strong hypotheses that precedes debates: a dedicated search per open checklist alternative |
| Filtering | reviews advisory, no gate | admission (spec 4a) and a factual gate: a refuted outcome, mechanism or premise filters (spec 8); nothing disappears silently (spec 10) | v2: `rules.admit`, `rules.evidence_profile` (gate, `gate_reason`); lists `awaiting_refinement`, `unparsed`, `directions` with counts in the result |
| Proximity | embeddings (section 6.5) | typed proximity from the card (spec 8b); embeddings only as an approximation for unresolved entities | **not yet**: identifiers are resolved (PubChem, ChEBI, ChEMBL), the typed relation function (`duplicate`, `variant`, `competitor`, ...) is not written; `competitor` alternatives wait for it |
| Leakage probe | `hyparena/leakage.py`, `--exclude-known` | dropped; may stay switched off | kept for the old ladder, not used by v2 or `hyparena/outcomes.py`; models are chosen by cutoff ≤ T |
| Expert in the loop | not in v1, no fields reserved (section 10) | expert layer (spec 7a), `Prefer` constraints (Aggregation_Spec 6a) | v2: `hyparena/card/expert.py` (decisions, expert hypotheses `origin: expert`, sources for claims, `Prefer` constraints from pairwise decisions); `check_feasible` and `next_pair` in `hyparena/aspid.py` |
| Backtest | ITP pool from DrugAge, label "significant increase", fresh slice (section 8a) | A2: ITP + CITP, template hypotheses, evidence ≤ T, labels supports / no effect / harmful, repeats separate, clean and historical sets, post-2022 outcomes from the papers | `hyparena/outcomes.py` + `data/backtest/outcomes_itp_citp.yaml` (59 tests, 2022–2026), `backtest build-itp` (historical, per regimen, three labels); metrics AUC, Spearman with effect size, precision@k, calibration of P(A > B) |

Consistent already: judges and verifiers from families other than the writer's, both Co-Scientist baselines, comparison at an equal token budget.

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
| (none) | `normalize` | **New.** Extracts a hypothesis card (schema in `configs/card.yaml`) from the free text, flags missing required fields, suggests search queries, keeps the original text |
| (none) | `retrieve` | **New.** Literature evidence per hypothesis (`SearchTool`; Europe PMC first), restricted to `as_of` for backtests; read by reviewers and judges |
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

## 3a. Configurable criteria, card and evidence

The comparison format is not fixed yet, so three things are data, not code:

- **Criteria** (`configs/criteria.yaml`): name, description, and either an `importance` order (default) or explicit weights. Judges return 1 or 2 per criterion in one call; each criterion has its own Bradley–Terry rating. The final order is the expected score of a randomized aggregation (`hyparena/aggregate.py`). It is based on МРСП, not a reproduction of it:
  - **taken from МРСП:** only an order of importance is given, and the weight vector is random and uniform over all vectors consistent with it; output is the expected score, its spread and the probability that one object dominates another;
  - **our adaptations:** the indicators come from pairwise ratings. Each criterion's indicator is the **expected share of wins against the other hypotheses of the same pool**, under the rating system's own win probability (Bradley–Terry and Elo: logistic; TrueSkill: its Gaussian formula), instead of a normalization function of a declared type. It is computed in every Monte Carlo sample from ratings drawn within their uncertainty (Bradley–Terry: standard error; TrueSkill: σ; Elo, which has none: a bootstrap of the match log), so the spread carries the uncertainty of the tournament as well as of the weights. The report adds a 90% rank interval and per-criterion shares with intervals; pair selection uses the expected (rank-order centroid) weights. Pools above 200 hypotheses use a random subset of 200 opponents per sample.
  - **what the numbers mean:** scores and shares depend on the pool and on the judges, so they compare hypotheses within one run only. Systems are never compared by these numbers but by external labels (AUC, hit@1, MRR, rank correlation; `docs/comparison.md`). Elo and TrueSkill are kept only as the baselines' own mechanics, and each baseline's final order is its own rating order. The **match log is the source of truth**: ratings and the aggregation can be recomputed from it (`showcase --render … --reaggregate`). For pools that must be compared with each other (e.g. generated in different runs), a fixed set of anchor hypotheses played in every tournament would tie the scale (not implemented).

  References: Hovanov N. V., *Analysis and synthesis of indicators under information deficit* (Хованов Н. В., «Анализ и синтез показателей при информационном дефиците», St Petersburg University, 1996); Lahdelma R., Hokkanen J., Salminen P., SMAA, *European Journal of Operational Research*, 1998. Bibliographic details to be checked before publication. Default: novelty, evidence support, testability, value. `configs/criteria-two-axes.yaml` keeps the earlier promise/feasibility setup. The criteria and their version are stored in the plan, so a checkpoint keeps them.
- **Card schema** (`configs/card.yaml`, a draft): field name, type (text or list), required, description. The normalizer prompt and the judges' view are built from it. Everything in the card is **declared** by the hypothesis; required fields the text does not state are listed in `gaps`, never invented.
- **Evidence** (`hyparena.state.Evidence`): a uniform record for any source: `source`, `record_id`, title, excerpt, URL, `publication_date`, retrieval time, query, `tier`, study type, species, licence, entity ids. Only `source` and `record_id` are required. Tiers: 1 curated with explicit criteria, 2 peer-reviewed text, 3 text-mined relations, 4 preprints; LLM output is never evidence. The `as_of` date restricts retrieval to publications on or before it.

The verified layer (each declared sub-claim linked to evidence with a status) is the next step and waits for the card format.

- **Epistemic type of evidence** (from the data-source notes): every record says what its source can assert: `primary_text` (a paper's own text), `review_text` (background), `curated_record` (Open Genes, DrugAge: a signal, not proof), `measurement` (an executed test on data), `machine_derived` (text-mined relations: leads, never evidence), `quality_metadata`, `plans` (registry entries: plans and status, not results). Judges and reviewers see the type next to each record (`compare/v4`, `debate/v4`, `review_full/v4`).

## 4. Graph

```
   goal ─► parse_goal ─► supervisor ◄──────────────────────────────────────┐
                             │ continue                                    │
                             ▼                                             │
   generate ─► normalize ─► retrieve ─► review ─► proximity ─► tournament  │
                                                                  │        │
                                                   evolve ◄───────┘        │
                                                     │                     │
                                                     ▼                     │
                                                 meta_review ──────────────┘
                             │ stop
                             ▼
   report (ranking per criterion, Pareto front, research overview, pending)
```

- **Routing.** After `parse_goal`, the `supervisor` decides through a conditional edge whether to run another cycle or stop (section 6.9); it does not yet choose between agents by statistics. A cycle is: generate, normalize, retrieve, review, proximity, tournament, evolve, meta-review.
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
1. **Initial review** (no tools): correctness, quality, novelty, preliminary safety. In the paper a cheap filter that rejects obvious failures.
2. **Full review** (with search): the same criteria with retrieved literature. Novelty is judged **only** with retrieval (the paper's ablation: 6.14/10 without, 2.38/10 with).
3. **Deep verification**: decompose into assumptions and sub-assumptions, check each independently. Failures are marked fundamental or not.

**Reviews do not filter by default** (`review_gate: advisory`, decision 2026-10-15): every hypothesis is ranked as an ordinary one, and the judges see the reviewers' remarks (and a note when deep verification found a possible fundamental flaw). Only a failed safety check removes a hypothesis. The paper's behaviour, where the thresholds and a fundamental flaw reject before ranking, is `review_gate: reject` (`live run --review-gate reject`). Reason: in the negative-sampling test the gate made the ranking decision for almost every item and left the tournament nothing to compare (`docs/negative-sampling.md`, section 5); the criteria already include novelty and evidence support.

**Reviewers never come from the writer's family**, also when the client falls back to another family after a failure (`avoid`), because the judges read the reviews. Observation, simulation and recurrent reviews are later additions. Every claim in a review carries a citation or the label "assumption". A grounding check (citation exists and supports the claim) can run as the `review` function of a refine loop.

### 6.5 `proximity`
(Baseline graph. Method v2 replaces this by typed proximity from the card, spec 8b, not implemented yet.) Embeds hypotheses (an `Embedder` interface, stubbed), builds a neighbour graph and clusters, and merges near-duplicates above a threshold (merged ones stay in the log with `status = merged` and a pointer). Clusters are used by pair selection and by final diversification.

### 6.6 `tournament`
(Baseline graph and ablations only; method v2 ranks by rules and АСПИД.) The core node of the graph. One round:
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
Pareto front over the criteria, the final order by МРСП (expected score, spread, rank interval, dominance probabilities among the shown hypotheses), near-duplicates removed using clusters, and for each shown hypothesis: the original text, the record, reviews with citations, the match history, and the full provenance. A **research overview** (the Meta-review agent's final output in Co-Scientist) is written from the shown hypotheses: research areas, first experiments, conflicts and overlaps, open risks (`research_overview/v1`). Hypotheses that were never evaluated are listed as `pending`.

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
- **Tools.** `SearchTool.search(query, limit, as_of) -> list[Evidence]`; `--search` picks sources (`hyparena/tools/registry.py`), `MultiSearch` merges them. Connectors, all without keys:
  - **Europe PMC**: abstracts, first publication date, licence; `as_of` becomes a `FIRST_PDATE` range. The main source for dated retrieval.
  - **PubTator3**: articles with normalized entities (`entity_ids`, e.g. `CHEMICAL:MESH:D020123`). **Not usable under `as_of`**: its search favours recent papers and has no server-side date filter that I found (the first 50 results for "rapamycin lifespan mice" were all after 2015), so it returns nothing in backtests.
  - **Open Genes** (a curated database of ageing-related genes): gene symbols found in the query; tier 1. No per-entry dates, so it returns nothing under `as_of`.
  - **ClinicalTrials.gov v2**: registry records; `as_of` filters by first submission date, but the status and completion shown are today's, which can leak later developments (flagged in the record).
  - **Retraction check** (`hyparena/tools/retractions.py`): the Retraction Watch CSV (download with `python -m hyparena.tools.retractions download`); evidence whose DOI or PMID was retracted is flagged and hidden from reviewers and judges, counting only retractions dated on or before `as_of`.
  Retrieval quality (recall, relevance) has not been evaluated: unfiltered queries tend to return recent reviews.
- **Embeddings.** An `Embedder` interface, stubbed first.

## 8a. Backtest harness

`hyparena/backtest.py` builds a labelled pool as of a date T and evaluates a run against labels the pipeline never sees.

- **Historical ITP pool** (`build-itp --as-of T`): ITP tests from DrugAge rows flagged ITP, one per compound and regimen (dosage, age at initiation); a test enters if its first ITP publication is after T (dates from PubMed via E-utilities, the earliest public date). Labels supports / no_effect / harmful, with the result per sex and the effect size apart; a repeat at another dose or start age is its own hypothesis. For T = 2010-12-31: 70 tests (27 supports, 40 no effect, 3 harmful). The hypothesis text states the intervention and the regimen, not the outcome. Templated items differ only in a name, so the dataset turns deduplication off.
- **Post-2022 pool** (`python -m hyparena.outcomes build --as-of T`): ITP and CITP tests from the batch papers (DrugAge has few entries after 2022), curated in `data/backtest/outcomes_itp_citp.yaml` with verbatim quotes (`outcomes check`). Each test is `clean` (public after the latest cutoff of the models compared) or `historical`.
- **Evaluation**: `evaluate --labels --result` for the ladder format (AUC of the combined score and of each criterion, precision in the top quarter); `outcomes metrics --labels --v2` for method v2 (AUC supports vs the rest, Spearman correlation with the effect size, precision@k, calibration of pairwise P(A > B)).
- **Leakage** (Working_Notes A1, A2): models are chosen by training cutoff ≤ T (`configs/model_cutoffs.yaml`; heuristic cutoff = release date − 6 months; `outcomes models --as-of T`). Baselines are compared on the clean set only; the historical set is for our system, whose evidence is cut at T. The leakage probe is not used.

## 8b. Co-Scientist baseline mode

`python -m hyparena.live run --mode coscientist`: one model family for every role, judges' independence rule off, a single holistic criterion (`configs/criteria-coscientist.yaml`, following the paper's default criteria), online Elo from 1200 (K = 32; the paper does not give K), pairing that favours new and top-ranked hypotheses and similar ones (same proximity cluster), judges that see only the text and the reviews (`cs_compare`, `cs_debate`, adapted from the paper's prompts; JSON output instead of the paper's "better idea: 1 or 2"). Reviews still use retrieval, as the paper's full review searches the literature. Compare with our mode at an **equal token budget** (`--max-tokens`): our mode spends more judge calls per match.

**Second baseline, the 2026 version** (arXiv 2608.26701, `--ladder L0ts` or `--mode coscientist-2026`): as L0, but ratings are TrueSkill (Gaussian skill per hypothesis, updated after each comparison; the paper gives no parameters, so TrueSkill's defaults are used: μ 25, σ 25/3, β σ/2, τ σ/100, no draws), and contenders are chosen by UCB = μ + κσ with κ = 1, so new, uncertain hypotheses play first. In the paper UCB selects parents for evolution; here, with external hypotheses and no evolution, it selects who plays. The paper's plagiarism penalty and hallucination clipping concern generation and manuscripts and are not reproduced.

## 8c. Comparison tooling

The protocol is in [`comparison.md`](comparison.md): ablation ladder L0–L4 (`hyparena/ladder.py`, `live run --ladder`), dev/test splits in the labels, the leakage probe (`hyparena/leakage.py`; not used for method v2, Working_Notes A1), the run grid (`hyparena/experiment.py`), paired comparison with bootstrap (`backtest compare`), and `--fake` for running all of it without model calls. The tournament stops scheduling matches when the token budget is spent.

## 9. Package layout

```
hyparena/
  sim.py                 # existing simulation (kept as is)
  state.py               # state, hypothesis, provenance, match, rating
  graph.py               # LangGraph assembly: nodes, edges, checkpointer
  schema.py              # criteria and card schema loaded from configs/
  agents/
    supervisor.py  parse_goal.py  generate.py  normalize.py  retrieve.py  review.py
    proximity.py   tournament.py  evolve.py    meta_review.py  report.py
  llm/
    client.py            # LLMClient, Reply, runner wiring, token estimation
    judges.py            # family pool, eligibility, sampling
  rating.py              # Bradley–Terry, pair selection (from sim.py)
  backtest.py            # ITP pool as of a date, evaluation against hidden labels
  tools/
    search.py  registry.py  europepmc.py  pubtator.py  opengenes.py  clinicaltrials.py  retractions.py  http.py
    embed.py             # Embedder interface + hashing stub
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
- Expert-in-the-loop input in this graph. (Changed 2026-10-19: method v2 has the expert layer, `hyparena/card/expert.py`.)

## 11. Decisions and open questions

Decided:
1. **Lineage strictness:** the looser `writer` mode is the default; `lineage` is available.
2. **Expert in the loop:** not in this graph; in method v2 as the expert layer (spec 7a).

Open:
1. **Per-axis debate.** Whether a debate should be run per axis or once for both axes (the skeleton runs once for both).
2. **Rating when axes disagree.** Resolved for now by an order of importance and МРСП aggregation (decision 2026-10-15); the order lives in the criteria file and should be set with experts. The indicator is the expected win share against the pool (decision 2026-10-16), comparable within a run only.
3. **Cost caps.** The skeleton caps tokens (estimated) and cycles; the budget unit and defaults are placeholders.

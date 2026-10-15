# Ranking thousands of hypotheses: a Co-Scientist-based approach

Task: from N ≈ 10³–10⁵ biological hypotheses (domain: ageing) that **arrive from outside** (LLMs generate them in volume), select the most **promising** ones, with an explanation that can be verified against sources. **Ranking is the focus.** Generation and evolution stay in the graph as optional modules (off when hypotheses are imported), because the stages interact: what is retrieved and reviewed is what the judges rank.

The honest claim is "our selector picks better from a given pool", measured against an independent signal at equal LLM-call budget, not "a better system than Co-Scientist overall".

Details of how Co-Scientist itself works (hypothesis format, judges, criteria) are in [`co-scientist-reference.md`](co-scientist-reference.md).

## 1. What we take from Co-Scientist

Co-Scientist (Google, 2025) ranks hypotheses with an Elo tournament of pairwise LLM comparisons. We reuse the ideas below and change what the paper does not cover.

| Co-Scientist idea | What we do |
|---|---|
| Elo tournament of pairwise LLM comparisons | Pairwise comparisons plus a **Bradley–Terry** model instead of online Elo. It gives an uncertainty estimate, which we need to choose the next pairs |
| Proximity graph | Embeddings and clusters. Duplicates are merged, and comparisons mostly happen between topically close hypotheses |
| Reflection (reviews), debate for top pairs | Structured, search-grounded review before the tournament. Debate only for top and contested pairs |
| Single Elo over configurable criteria (feasibility can be one attribute); TrueSkill + UCB in the 2026 version | **One rating per criterion** (criteria in `configs/criteria.yaml`; default: novelty, evidence support, testability, value), combined **without numeric weights**: only an order of importance is set, and the final order comes from randomized aggregation (МРСП) with spreads and dominance probabilities; the Pareto front is shown |
| One model family for generator and judges | **Judges come from other model families than the generator.** An ensemble of several families, because errors within a family are correlated |

We also add **verifiable output**: every verdict carries citations and a "fact / assumption" label.

## 2. Why not "score each hypothesis 1–10"

- Absolute LLM scores are poorly calibrated and cluster in a narrow range.
- Pairwise comparison is more stable: relative judgments are easier for a model than absolute ones.
- The cost of pairwise comparison is the number of comparisons. Full round-robin for N = 2000 is about 2 million calls (1000 per hypothesis). We need adaptive pair selection.

### Judge independence rule

- Every hypothesis records the **model (family) that generated it** as provenance metadata.
- For a given hypothesis, judges are taken only from **other families** than its generator. When a pair mixes two generators, judges must differ from both.
- If the generator is unknown (for example, imported or human-written text), we cannot exclude any family, so we still use **several different families** as judges and compare their agreement.
- This is cheap to implement, needs no extra data, and removes the most direct source of self-preference and correlated errors. It does not remove bias shared across all LLMs, so expert labels are still needed (section 7).

### Judge ensemble (design)

**Candidate families** (the starting pool; one model per family):

| Family | Vendor | Weights | Notes |
|---|---|---|---|
| GPT | OpenAI | closed | |
| Claude | Anthropic | closed | |
| Gemini | Google | closed | Generator family of Co-Scientist, so it needs the independence rule when Co-Scientist-like generators are used |
| Qwen | Alibaba | open | Can be self-hosted |
| DeepSeek | DeepSeek | open | Can be self-hosted |
| GLM | Zhipu | open | Can be self-hosted |
| MiMo | Xiaomi | open | Used as an independent judge in the HypoEval benchmark |
| Grok | xAI | closed | |
| Muse | Meta (Muse Spark) | closed | API availability reported as limited and staged; availability must be checked against Meta's own documentation |

Other candidates to consider later: Kimi (Moonshot), MiniMax, Mistral, ByteDance Seed (used as the main judge in HypoEval). Biomedical specialist models (for example MedGemma) are likely weak as judges and are at most an extra signal.

**Rules:**
1. **Independence.** The judge rule above applies. Exactly one model per family: different sizes or reasoning modes of one family are not independent.
2. **Different vendor is not the same as independent.** Models are often trained on each other's outputs, so errors can still correlate. Independence is measured, not assumed: on the calibration set (see section 7), compute each judge's agreement with experts per axis and the correlation of errors between judges, and choose the ensemble by marginal contribution, not by individual accuracy.
3. **Tiers.** Cheap or open models run the early rounds. Stronger and different models judge the top and contested pairs, which matches the debate logic of Co-Scientist.
4. **Provenance.** For every verdict record the exact model identifier and version, the prompt version and the rubric version. API model versions change and get retired, so rankings are reproducible only if this is recorded.
5. **Privacy.** Unpublished hypotheses should go only to approved providers. Open-weight families can be self-hosted, which removes the question. Which hosted APIs are acceptable has to be decided up front.
6. **Selection of the pool is provisional.** General capability leaderboards do not measure judging of novelty and feasibility in biomedicine. The pool is a starting point, to be pruned using the calibration set.

## 3. Pipeline

```
hypotheses → [1] normalization → [2] enrichment/RAG → [3] rubric review
           → [4] dedup/clusters → [5] tournament (2 axes) → [6] debate on top
           → [7] Pareto front + diversification → report for scientists
```

1. **Normalization.** Each hypothesis is converted to a schema: claim, mechanism, prediction, how to test, organism/model.
2. **Enrichment (RAG).** Search PubMed and patents. Output: what is already known, what contradicts, nearest prior work. This grounds novelty and evidence-base assessment. Co-Scientist's own ablation shows why: without search, known ideas were scored 6.14/10 for novelty, with search 2.38/10.
3. **Rubric review** (single scoring for cheap filtering and initial ratings):
   - promise: novelty, evidence base, explanatory power, potential impact;
   - feasibility: experimental testability, available methods and model systems, cost and time, ethics and risk;
   - each statement is labelled with a source or "assumption".
4. **Deduplication.** Hypotheses closer than a cosine-similarity threshold are merged. Clusters are also used to diversify the final list.
5. **Tournament.** Section 4.
6. **Debate.** For top pairs where the judge is uncertain, or where the verdict flips when A/B order is swapped, run a multi-turn debate as in Co-Scientist. It is expensive, so it is applied only there.
7. **Result.** The final order comes from randomized aggregation over all weight vectors consistent with the order of importance of the criteria (МРСП, Hovanov's АСПИД methodology; analogue: SMAA; `hyparena/aggregate.py`): expected score, spread, 90% rank interval and the probability that one hypothesis outranks another. The person ranking sets only the order (current default: value ≥ evidence support ≥ testability ≥ novelty, decision 2026-10-15, to be revisited with experts), not numbers. The Pareto front is shown as context. Near-duplicates are removed from the top using clusters.

## 4. Tournament: avoiding N² comparisons

- **Model.** Bradley–Terry per axis. One judge call returns verdicts on both axes.
- **Pair selection.** We need a reliable **top-k**, not a perfect order of all N. We use elimination: a hypothesis whose upper bound (rating + z·SE) is below the k-th best lower bound needs no further comparisons. The remaining candidates are compared with neighbours in rating. 20% of the budget goes to a uniform Swiss round, so that a wrongly underrated hypothesis is not lost.
- **A/B order.** Order is randomized, and contested pairs are run twice with positions swapped. Co-Scientist reports a "second player advantage" for a simple comparison prompt and that a debate prompt almost removes it, so this must be checked on any real judge.
- **Budget.** About 10–20 comparisons per hypothesis instead of N/2. For N = 2000 that is 2·10⁴–4·10⁴ calls instead of 2·10⁶. For N = 10⁵, round-robin (5·10⁹) is impossible.

## 5. Prototype and simulation results

`hyparena/sim.py` (numpy, `python -m hyparena.sim`). Synthetic population: N = 2000, latent "true" scores on two axes with correlation −0.3 (promising ideas are often less feasible). The judge is a sigmoid of the score difference with temperature 1.0 (very noisy) and a position bias of 0.3. Metrics: **recall**, the share of the true top 5% (k = 100) that is found; **ρ**, Spearman rank correlation over all hypotheses. Mean of 3 seeds; the final score is 0.5·promise + 0.5·feasibility.

| comparisons per hypothesis | random | swiss | active (elimination) |
|---|---|---|---|
| 2 | recall 0.23 / ρ 0.50 | recall 0.27 / ρ 0.55 | recall 0.28 / ρ 0.52 |
| 4 | recall 0.34 / ρ 0.65 | recall 0.37 / ρ 0.66 | recall 0.43 / ρ 0.66 |
| 8 | recall 0.46 / ρ 0.78 | recall 0.47 / ρ 0.77 | recall 0.58 / ρ 0.75 |
| 16 | recall 0.58 / ρ 0.88 | recall 0.60 / ρ 0.86 | **recall 0.73** / ρ 0.82 |

What the table shows:
- With 16 comparisons per hypothesis, adaptive pair selection gives top recall 0.73 against 0.58 for random pairs (+15 pp). Swiss is close to random.
- The price is the **tail**: overall Spearman is lower for active selection (0.82 vs 0.88) because poor hypotheses are barely compared. That is fine for "find the best", but the tail ranking must not be interpreted.
- Absolute recall at this judge noise stays moderate (0.73 at 16 comparisons). Reducing judge noise (debate, judge ensemble, rubric) matters as much as pair selection.
- Randomizing A/B order had a small effect in this simulation (up to about 5 pp recall, within seed-to-seed spread). Three seeds do not support a significance claim, so bias protection must be tested on a real judge.

## 6. Limitations and risks

- **Judge ≠ truth.** An LLM judge prefers long, smooth, familiar wording (risk of "beautiful but trite" hypotheses) and may invent sources. Mitigations: citation check via RAG, "fact / assumption" labels, length and style normalization before comparison. Co-Scientist's own validation is modest: review scores predict correctness with AUC of only about 0.64–0.65 on GPQA, and its Elo is not tied to ground truth.
- **Synthetic data does not prove real-world quality.** The simulated judge is independent and homogeneous; real LLM errors are correlated. The simulation tests only the pair-selection mechanics.
- **Criteria conflict.** Hence per-criterion ratings, not a single score, and an order of importance instead of hand-set weights. With four or more criteria the Pareto front stops discriminating (in a small test, all 12 active hypotheses were on it), so the combined score and the per-criterion intervals carry the ranking; the front is context.
- **Judge novelty can mislead.** HindSight (2603.15164, from the working notes) reports a negative correlation between an LLM judge's novelty rating and later impact (ρ = −0.29, ML ideas). Novelty is therefore judged only against the retrieved evidence, and its place in the order of importance should be checked by the backtest, not assumed (in the negative-sampling test its AUC was 0.52, no signal).
- **Novelty.** It is assessed against retrieved literature, and RAG is incomplete. Low novelty caused by poor retrieval will unfairly lower a rating.

## 7. Validation without expert labels

Decision (working notes): expert labels are **not assumed**; they are an optional top tier. Ground truth comes from non-human sources, and agreement between LLM judges is not validity.

1. **Time-split backtest.** Hypotheses or claims stated before a date T, ranked with evidence restricted to T (`RunConfig.as_of`, applied in retrieval), against what the literature showed after T. Labels are later support or refutation, not a judge's opinion.
2. **Replication and outcome labels.** Interventions with known fate: NIA ITP results, DrugAge records (dates derived from PubMed ids, since DrugAge has no entry-date column), trial registry outcomes and statuses.
3. **Hidden holdout.** A labelled set that the selector and the judges never see; metrics are computed outside the pipeline (AIRA²'s hidden consistent evaluation).
4. **Judge checks without labels:** position-swap consistency; sensitivity to style (same content, different phrasing or format); cross-family agreement as a sanity check only; accuracy on the backtest labels.
5. **Baselines at equal budget:** direct 1–10 scoring; a Co-Scientist-like tournament (one Elo, one model family, holistic verdict); our tournament without evidence; single judge vs. ensemble. Report cost per run.
6. **Leakage.** A judge or generator whose training cutoff is after T can know the outcome; use models with an earlier cutoff for backtests or test for leakage.
7. **Negative sampling.** A confirmed finding hidden among nine plausible false statements (real negatives from DrugAge and model-generated variants checked by another family); hit@1, MRR and errors per kind of negative (`docs/negative-sampling.md`). Cheap and scalable, but it measures telling true from false, not prioritising open hypotheses.
8. **Experts, when available:** a small set of pairwise preferences as the top validation tier, with inter-expert agreement as the ceiling.

## 8. Next steps

1. Done: Europe PMC, PubTator3, Open Genes, ClinicalTrials.gov connectors and the Retraction Watch check (architecture, section 8). Next: evaluate retrieval quality; PubTator3 entity normalization of the card; date-aware sources for curated databases.
2. Verified layer of the card: each declared sub-claim linked to evidence records with a status (established, supported, contested, speculative, refuted), once the card format is agreed.
3. Done: the ITP backtest harness (architecture, section 8a). Next: run it with judges whose training cutoff precedes T, add more label sources (trial outcomes, other DrugAge species), and check the order of importance of the criteria against the labels on a held-out split.
4. Cost and time of the decisive experiment from registries (reference classes), reported as intervals, instead of being judged.
5. Done: the Co-Scientist baseline mode (architecture, section 8b). The comparison itself is **postponed** (decision 2026-10-14): the project is still in development, and on the current ITP pool any result would be contaminated by what the models already know.
6. **Beta: memorization not handled** (decision 2026-10-14): the current ITP pool is used as it is; results are an upper bound. Later: **fresh slice, accumulated over time.** Keep collecting labelled outcomes published after the training cutoff of the judge models (new ITP and DrugAge results, trial outcomes), and rebuild the pool with T set after the latest cutoff (`build-itp --as-of <cutoff>`). Run the comparison once that slice is large enough to give useful intervals.

## 8a. Lines of work (from the working notes, 2026-10-15) and where the code stands

The working notes split the project into three nested lines; stage 1 is line 1 plus thin versions of lines 2 and 3.

| Line | Content | In the repository | Not yet |
|---|---|---|---|
| 1. Improve on Co-Scientist | reimplemented baseline, new mechanisms, evaluation infrastructure, cost and time of the decisive experiment | both baselines (L0 Elo 2025, L0ts TrueSkill + UCB 2026), ablation ladder, per-criterion Bradley–Terry, МРСП aggregation, independent judge ensemble, advisory reviews, ITP backtest, negative-sampling test, leakage probe | cost and time of the decisive experiment (item 4 above); runs at a scale that gives usable intervals |
| 2. Structure of hypotheses and data | card v2 (narrative, PICO, claim graph), evidence record with verbatim quote and role, declared vs verified layers, judge packet | card draft-1 (declared layer only, from config); evidence records with source tier, date, retraction flag and epistemic type (six types from the notes) shown to the judges | claim graph, quotes and roles, verification statuses: wait for the card v2 decisions |
| 3. Own knowledge graph | observation-level graph on lifespan over Open Genes and HAGR, temporal snapshots | connectors to Open Genes, DrugAge (backtest and negative sampling), Europe PMC, PubTator3, ClinicalTrials.gov | everything else; MVP slice proposed in the notes: mTOR interventions and senolytics |

A finding from the negative-sampling test that bears on line 2: judges most often prefer a variant that adds a false mechanism to a true effect. Splitting a hypothesis into claims and checking each link separately is the direct remedy.

## 9. Example input data: a ChatGPT dialogue

`data/chatgpt_hypotheses.json` holds 27 hypotheses on the biology of ageing, taken from a [shared ChatGPT dialogue](https://chatgpt.com/share/6ace78ee-56bc-83e8-9134-845f5d47a778) (the dialogue asks six times to "continue", the last time to "raise the level of surprise"). The text is in Russian, as in the source. The parser is `scripts/parse_chatgpt_hypotheses.py`. The dataset's `source` field records the writer (`family: openai`, `model: gpt-6-astra-wm`, read from the dialogue's own metadata), which the judge independence rule needs. `hyparena/data.py` loads the dataset into the graph as imported hypotheses, and `python -m hyparena.live run --import-file data/chatgpt_hypotheses.json --limit 8` runs them through normalization, review and the tournament.

**Record schema** (a candidate for the normalization schema in section 3):

| Field | Content |
|---|---|
| `title`, `claim` | title and the claim with its mechanism |
| `known` | what is already known, separating published findings from assumptions |
| `experiment` | the deciding experiment (model, groups, controls, timing) |
| `prediction` | the specific prediction |
| `falsification` | what would refute the hypothesis |
| `intervention` | potential intervention (present in all 27) |
| `message` | index of the reply in the dialogue, that is, generation order |

`assistant_notes` stores the assistant's closing remarks for each batch (which hypotheses it recommends testing first). This is a ready-made **model self-assessment** to compare with the tournament result.

**What this means for the system:**
- All hypotheses are written equally smoothly and contain an experiment and a refutation condition, so scoring "by text" will barely separate them. The rubric must look at content: is there a direct causal test, how strong is the evidence in `known`, is there contradicting evidence (in hypothesis 27, `known` itself points to such evidence).
- A series of "continue" requests with a request for surprise pushes the stream towards exotic ideas. `message` makes it possible to check whether promise and feasibility diverge later in the series.
- Some hypotheses are near-duplicates by topic (mitochondria and lysosomes, transcription of long genes, thymus), which suits a test of deduplication.

**Dataset limitations.** Source references from the export cannot be recovered (only internal markers remained, and they were removed), so `known` cannot be checked against literature without a separate search. I did not check the scientific correctness of the claims. The dialogue contains no scores. 27 hypotheses is a lot to read manually but too few to test a tournament: scale is tested by the simulation in section 5.

## 10. Existing Co-Scientist implementations

Google has not published Co-Scientist code (the README of one reimplementation says the original is closed-source). There are third-party reconstructions based on the paper. I only looked at the repository pages and did not check code quality, licences or activity, so check them before use:
- [jataware/open-coscientist](https://github.com/jataware/open-coscientist): LangGraph, generation, review, ranking and evolution of hypotheses, with biomedical configurations.
- [Kaimen-Inc/Co-Scientist](https://github.com/Kaimen-Inc/Co-Scientist): several LLM backends (including Anthropic), based on the pseudocode in the paper's supplement.
- [DawnyWu/Co-Scientist](https://github.com/DawnyWu/Co-Scientist): same description as Kaimen-Inc, with a mode that compares models through a shared Elo tournament.
- [llnl/open-ai-co-scientist](https://github.com/llnl/open-ai-co-scientist): Lawrence Livermore National Laboratory, Gradio interface, MIT.
- [The-Swarm-Corporation/AI-CoScientist](https://github.com/The-Swarm-Corporation/AI-CoScientist): minimal implementation on the Swarms framework, MIT.
- [conradry/open-coscientist-agents](https://github.com/conradry/open-coscientist-agents): LangGraph and GPT Researcher, archived.

These projects implement the general "agents + Elo tournament" design. The prototype in `hyparena/` addresses a narrower question: how to save comparisons with thousands of hypotheses and keep two axes.

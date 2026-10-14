# Ranking thousands of hypotheses: a Co-Scientist-based approach

Task: from N ≈ 10³–10⁵ generated biological hypotheses (domain: ageing), select the most **promising** ones that are also **feasible**, with an explanation that can be verified.

Details of how Co-Scientist itself works (hypothesis format, judges, criteria) are in [`co-scientist-reference.md`](co-scientist-reference.md).

## 1. What we take from Co-Scientist

Co-Scientist (Google, 2025) ranks hypotheses with an Elo tournament of pairwise LLM comparisons. We reuse the ideas below and change what the paper does not cover.

| Co-Scientist idea | What we do |
|---|---|
| Elo tournament of pairwise LLM comparisons | Pairwise comparisons plus a **Bradley–Terry** model instead of online Elo. It gives an uncertainty estimate, which we need to choose the next pairs |
| Proximity graph | Embeddings and clusters. Duplicates are merged, and comparisons mostly happen between topically close hypotheses |
| Reflection (reviews), debate for top pairs | Structured, search-grounded review before the tournament. Debate only for top and contested pairs |
| Single Elo over configurable criteria (feasibility can be one attribute) | **Two separate ratings**, promise and feasibility, combined on a Pareto front |
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
7. **Result.** A Pareto front over the two axes. Selection from the front uses weights set by the person ranking (for example, "early screening" weights feasibility more, "grant-ready" weights promise more). Near-duplicates are removed from the top using clusters.

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
- **Promise and feasibility conflict.** Hence a front, not a single score, with weights visible to the user.
- **Novelty.** It is assessed against retrieved literature, and RAG is incomplete. Low novelty caused by poor retrieval will unfairly lower a rating.

## 7. Validation with domain experts

1. **Gold set.** 50–100 hypotheses labelled on both axes by 2–3 experts. Metrics: judge–expert agreement (Spearman, share of matching pairs), with inter-expert agreement as the ceiling.
2. **Baselines:** direct 1–10 scoring with one prompt; a tournament without the similarity graph; a tournament without debate; a single-model judge vs. an ensemble. Same metrics plus token cost.
3. **Robustness.** Swap A/B order, change rubric wording, change the judge model, rerun with another seed. Report the share of pairs whose verdict changes.
4. **Retrospective.** Take hypotheses whose test is already published and see where the system ranks them.
5. **Practical metric.** The share of top-k hypotheses that domain experts agree to take into an experiment.

## 8. Next steps

1. Replace the `Judge` stub with a real LLM judge using a rubric and JSON output (verdict per axis, citations, "fact / assumption" labels).
2. Connect RAG over PubMed and patents, compute embeddings, build the similarity graph.
3. Build the gold set with domain experts and measure judge agreement.
4. Add debate for contested pairs and a judge ensemble. Measure recall gained per token.

## 9. Example input data: a ChatGPT dialogue

`data/chatgpt_hypotheses.json` holds 27 hypotheses on the biology of ageing, taken from a [shared ChatGPT dialogue](https://chatgpt.com/share/6ace78ee-56bc-83e8-9134-845f5d47a778) (the dialogue asks six times to "continue", the last time to "raise the level of surprise"). The text is in Russian, as in the source. The parser is `scripts/parse_chatgpt_hypotheses.py`.

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

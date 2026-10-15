# Negative-sampling test

Status: tooling ready; a first small run on cheap paid models (6 groups, one seed) is reported in section 5.

## 1. Question

Given a confirmed finding hidden among nine plausible but false statements, does the ranking put the finding first? This complements the ITP backtest (`docs/comparison.md`):

| | ITP backtest | Negative sampling |
|---|---|---|
| Measures | prioritising open hypotheses whose outcome was later known | telling a confirmed claim from plausible false ones |
| Labels | real outcomes, few (5 positives in the test split) | real for findings and real negatives, model-checked for synthetic ones; scales to hundreds of groups |
| Diagnostics | per criterion | per criterion and per kind of negative |

Telling true from false is necessary for good prioritisation but not sufficient: a system can catch fakes and still pick poorly among untested ideas. So this is a diagnostic test, not a replacement for the backtest.

## 2. Groups

Source: DrugAge (HAGR, CC BY 3.0), the same database as the ITP pool. Each group has ten statements about one species:

| Item | How many | Where from | Why it is false |
|---|---|---|---|
| Finding | 1 | a compound with a significant increase of average lifespan in ≥ 2 publications and no significant decrease | (true) |
| Variants of the finding | 2 | the writer model: reversed effect, wrong condition (sex, stage, background, dose), failed analogue, wrong mechanism | a verifier from another family calls it false with confidence ≥ 0.7 |
| Decoy | 1 | a real negative (below) | data |
| Variants of the decoy | 2 | the writer: reversed effect, a mechanism for an effect the compound does not have | data |
| Real negatives | 4 | compounds tested in the same species with no significant effect in any row | data |

**Why the decoy.** Without it, the finding would be the only compound named three times in the group, and "pick the centre of the cluster" would find it without any biology. With the decoy there are two clusters of the same size; the finding is in one of them.

**Style.** All ten statements are rewritten by the writer model in one call, in random order, in one fixed format (title, claim, prediction, experiment), without being told which is true and with an instruction not to mention prior results. All hypotheses in a group therefore have the same author and the same shape.

**Time.** Each group carries `as_of` = the day before the finding was first published; retrieval only returns evidence published by then. The judges' own memory is not cut (beta decision: memorization is not handled, so the numbers are an upper bound, more so here than for ITP because well-known findings such as spermidine in mice are likely memorised).

**Independence.** The writer's family never judges its group (`lineage_mode: writer` in L4; the single family of L0 must be another family, which `run` does not change: choose the writer accordingly). The verifier judges too; it saw the synthetic statements in a separate call and no state is shared.

## 3. Metrics

Per group, by the combined score (and per criterion with `--key`); unrated items (rejected at review) go to the bottom:

| Metric | Chance (10 items) |
|---|---|
| hit@1: the finding ranked first | 0.10 |
| MRR: mean of 1 / rank of the finding | 0.29 |
| mean rank of the finding | 5.5 |
| AUC: share of negatives ranked below the finding | 0.50 |
| the same share per kind of negative | 0.50 |

Means over groups with a bootstrap 95% interval over groups; `compare` gives a paired bootstrap of A − B over groups (seeds averaged per group).

A note on criteria: the full criteria set is used (`configs/criteria.yaml`), as for real use. A confirmed finding is not novel today, but with `as_of` before its publication the novelty judgement is made against the evidence of that time; a reversed or overstated claim may still look more novel. The per-criterion metrics show this.

## 4. Commands

```bash
# 1. groups (4 calls per group: generate and verify variants of the finding, generate decoy variants, rewrite)
ALLOW_PAID=1 python -m hyparena.negatives build --groups 6 --config configs/paid-test.yaml --writer zhipu --verifier google
# 2. one tournament per group and arm (prints the commands; --execute runs them, resumable)
ALLOW_PAID=1 python -m hyparena.negatives run --steps L0,L4 --seeds 0 --max-tokens 300000 --execute
# 3. baseline without a tournament: one call ranks the whole group
ALLOW_PAID=1 python -m hyparena.negatives listwise --config configs/paid-test.yaml --families openai,google
# 4. metrics and a paired comparison
python -m hyparena.negatives evaluate --runs runs/neg/L4_s0
python -m hyparena.negatives compare --a runs/neg/L4_s0 --b runs/neg/L0_s0
```

`--fake` on `build`, `run` and `listwise` exercises everything with the fake LLM at no cost.

## 5. First run (2026-10-15)

Six groups (worms 2, flies 2, mice 2), writer GLM-5.3-flash, verifier Gemini-3.1-flash-lite, judges gpt-5-nano (L0, the only family) and gpt-5-nano + Gemini (L4), one seed, Europe PMC as of the day before the finding. Estimated spend for everything below, including two discarded runs: about $0.35 (estimated tokens, without hidden reasoning).

| Arm | hit@1 | MRR | mean rank | AUC | finding survived review |
|---|---|---|---|---|---|
| chance | 0.10 | 0.29 | 5.5 | 0.50 | |
| one call, gpt-5-nano | 0.17 | 0.42 | 3.5 | 0.72 [0.56, 0.89] | |
| one call, Gemini flash-lite | 0.50 | 0.62 | 3.2 | 0.76 [0.48, 0.96] | |
| L0 (Co-Scientist-style) | 0.00 | 0.18 | 5.6 | 0.49 | 0 of 6 |
| L4 (full method) | 0.33 | 0.44 | 4.5 | 0.61 [0.41, 0.81] | 2 of 6 |

L4 − L0: MRR +0.26 [−0.02, 0.54], AUC +0.12 [−0.07, 0.32] (paired bootstrap over 6 groups; 90% of samples above zero). With six groups none of this is conclusive.

**The tournament was hardly tested.** The review gate rejected almost everything: in L0, 1 of 60 items survived; in L4, 8. Only two groups had a match at all. The ranking was therefore made by the gate, and items ranked by the gate tie at the bottom. In a diagnostic run of the spermidine group, L4 kept the finding (initial review 6, full review 9) and rejected all nine negatives. That is the right answer there, but it shows that the tournament has nothing left to rank. Reading per kind: the one-call baselines catch reversed effects and wrong conditions almost always. They are fooled by mechanism variants (the finding is ranked above them in 25–75% of cases), which add a plausible detail to a true effect.

**What the test found in the pipeline (fixed before the reported run):**
1. **Cut-off leak.** The evidence cut-off used PubMed's print date. Papers appear online weeks earlier, so the retrieval "as of" the day before a finding returned the finding's own paper (spermidine in mice: online 2016-11-14, print 2016-12). The cut-off now uses the earliest of the online, print and PubMed-entry dates. This also affects the ITP backtest.
2. **Missing evidence counted against a hypothesis.** When nothing was retrieved, the full review scored correctness and novelty 0 and rejected the hypothesis. Novelty now cannot reject without evidence (`review_full` v3), and the prompt says that missing evidence is not evidence against.
3. **Zeros copied from the example.** gpt-5-nano copied the zeros of the JSON example in the review prompt. The example now has placeholders, and the scales are defined.
4. **Bare claims are rejected, embellished ones pass.** A one-line claim without rationale got correctness 2, while a variant with an invented mechanism got 4. Every item now carries a rationale written the same way.

**Possible next steps:** run the same groups with the review gate advisory only (reviews shown to the judges, nothing rejected) to test the tournament itself; more groups and seeds for usable intervals.

## 6. Known limits

- **Synthetic labels are model judgements.** A variant of the finding is false because a verifier model says so, not because of data. The verifier is needed: in the first build it rejected as true 7 "condition" and 6 "analog" candidates the writer had offered as false (e.g. "17-alpha-estradiol extends lifespan … only in males", which matches the ITP result). But it errs too: it called "17-alpha-estradiol extends lifespan in Mus musculus by activating classical estrogen receptor alpha" false with 0.85 confidence, although published work ties the drug's metabolic benefits in male mice to that receptor (that candidate happened not to be used). Real negatives and decoy variants are false by the data.
- **"No significant effect" is not "no effect".** A real negative may have been underpowered; DrugAge records the published significance.
- **Mechanism variants contain the true effect.** "X extends lifespan through Y", with Y wrong, is false but says the true thing about lifespan. Ranking it above the finding is an error of a different kind than ranking a reversed claim above it; the per-kind numbers keep them apart.
- **Memorization** (section 2): not handled in the beta.
- **Species** with fewer real negatives than the group size are skipped (in the current release: rat, yeast), so worms, flies and mice dominate.

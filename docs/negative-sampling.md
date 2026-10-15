# Negative-sampling test

Status: tooling ready; a first small run on cheap paid models (6 groups, one seed) is reported below.

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

Run in progress; results will be added here.

## 6. Known limits

- **Synthetic labels are model judgements.** A variant of the finding is false because a verifier model says so, not because of data. The verifier is needed: in the first build it rejected as true 7 "condition" and 6 "analog" candidates the writer had offered as false (e.g. "17-alpha-estradiol extends lifespan … only in males", which matches the ITP result). But it errs too: it called "17-alpha-estradiol extends lifespan in Mus musculus by activating classical estrogen receptor alpha" false with 0.85 confidence, although published work ties the drug's metabolic benefits in male mice to that receptor (that candidate happened not to be used). Real negatives and decoy variants are false by the data.
- **"No significant effect" is not "no effect".** A real negative may have been underpowered; DrugAge records the published significance.
- **Mechanism variants contain the true effect.** "X extends lifespan through Y", with Y wrong, is false but says the true thing about lifespan. Ranking it above the finding is an error of a different kind than ranking a reversed claim above it; the per-kind numbers keep them apart.
- **Memorization** (section 2): not handled in the beta.
- **Species** with fewer real negatives than the group size are skipped (in the current release: rat, yeast), so worms, flies and mice dominate.

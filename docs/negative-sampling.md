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

**Style.** All ten statements are rewritten by the writer model in one call, in random order, in one fixed format (title, claim, rationale, prediction, experiment), without being told which is true and with an instruction not to mention prior results. All hypotheses in a group therefore have the same author and the same shape.

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

Six groups (worms 2, flies 2, mice 2), writer GLM-5.3-flash, verifier Gemini-3.1-flash-lite. Judges: gpt-5-nano in L0 (its only family); gpt-5-nano and Gemini in L4. One seed, Europe PMC as of the day before the finding, reviews advisory (nothing rejected), 4 cycles with 3 matches per hypothesis. Estimated spend: about $0.47 for this run (L0 about 100k and L4 about 220k estimated tokens per group) and about $0.35 for the earlier attempts (estimated tokens, without hidden reasoning).

| Arm | hit@1 | MRR | mean rank | AUC [95% CI] |
|---|---|---|---|---|
| chance | 0.10 | 0.29 | 5.5 | 0.50 |
| one call, gpt-5-nano | 0.17 | 0.42 | 3.5 | 0.72 [0.56, 0.89] |
| one call, Gemini flash-lite | 0.50 | 0.62 | 3.2 | 0.76 [0.48, 0.96] |
| L0 (Co-Scientist-style tournament) | 0.33 | 0.45 | 4.8 | 0.57 [0.28, 0.85] |
| L4 (full method) | 0.67 | 0.70 | 3.7 | 0.70 [0.37, 1.00] |

L4 − L0, paired over the six groups: hit@1 +0.33 [0, 0.67], MRR +0.25 [−0.01, 0.56], AUC +0.13 [−0.13, 0.44]; 78–92% of bootstrap samples above zero. Suggestive, not conclusive, with six groups and one seed.

**Rank of the finding per group** (L0 / L4): vitamin D3 in worms 7 / 10, black tea extract in flies 8 / 8, 17-α-estradiol in mice 3 / 1, ethosuximide in worms 9 / 1, carnosine in flies 1 / 1, spermidine in mice 1 / 1. L4 is bimodal: first in four groups, near the bottom in the two with weak, little-known findings. Those two findings are the kind a model is least likely to remember, which fits the warning that the numbers are an upper bound.

**Per criterion (L4, AUC):** testability 0.70, value 0.70, evidence support 0.63, novelty 0.52. Novelty carries no signal here, as expected for a test of true against false.

**Per kind of negative (L4, share ranked below the finding):** wrong condition 1.0, reversed 0.83, mechanism variant 0.75, decoy variants 0.67, real negatives 0.67. Real negatives (compounds that really were tested and failed) are as hard as the decoys. Mechanism variants are harder for the one-call baselines (0.25–0.75) and for L0 (0.25).

**The one-call baselines score higher AUC than either tournament** (0.72–0.76), at about 1% of the tokens. Possible reasons, not separated yet:
- a list of ten shows the clusters and the contrasts at once;
- pairwise judges see retrieved evidence as of the cut-off, which for obscure findings is little or off-topic;
- with six groups the difference is within noise.

This needs more groups before it means anything. If it holds, a cheap listwise pre-ranking ahead of the tournament is worth considering.

**Earlier attempt with the review gate on** (reviews rejected below the thresholds, as in the paper). The gate rejected almost everything: 1 of 60 items survived in L0 and 8 in L4, and only two groups had a match. The ranking was made by the gate. This led to the decision to make reviews advisory by default (`docs/architecture.md`, 6.4).

**What the test found in the pipeline (fixed before the reported run):**
1. **Cut-off leak.** The evidence cut-off used PubMed's print date. Papers appear online weeks earlier, so the retrieval "as of" the day before a finding returned the finding's own paper (spermidine in mice: online 2016-11-14, print 2016-12). The cut-off now uses the earliest of the online, print and PubMed-entry dates. This also affects the ITP backtest.
2. **Missing evidence counted against a hypothesis.** When nothing was retrieved, the full review scored correctness and novelty 0 and rejected the hypothesis. Novelty now cannot reject without evidence (`review_full` v3), and the prompt says that missing evidence is not evidence against.
3. **Zeros copied from the example.** gpt-5-nano copied the zeros of the JSON example in the review prompt. The example now has placeholders, and the scales are defined.
4. **Bare claims are rejected, embellished ones pass.** A one-line claim without rationale got correctness 2, while a variant with an invented mechanism got 4. Every item now carries a rationale written the same way.

**Possible next steps:** more groups (the current DrugAge release gives 76 with the current rules: 56 worm, 14 fly, 6 mouse) and three seeds for usable intervals; the same groups with the listwise baseline as a pre-ranking step.

## 6. Known limits

- **Synthetic labels are model judgements.** A variant of the finding is false because a verifier model says so, not because of data. The verifier is needed: in the first build it rejected as true 7 "condition" and 6 "analog" candidates the writer had offered as false (e.g. "17-alpha-estradiol extends lifespan … only in males", which matches the ITP result). But it errs too: it called "17-alpha-estradiol extends lifespan in Mus musculus by activating classical estrogen receptor alpha" false with 0.85 confidence, although published work ties the drug's metabolic benefits in male mice to that receptor (that candidate happened not to be used). Real negatives and decoy variants are false by the data.
- **"No significant effect" is not "no effect".** A real negative may have been underpowered; DrugAge records the published significance.
- **Mechanism variants contain the true effect.** "X extends lifespan through Y", with Y wrong, is false but says the true thing about lifespan. Ranking it above the finding is an error of a different kind than ranking a reversed claim above it; the per-kind numbers keep them apart.
- **Memorization** (section 2): not handled in the beta.
- **Species** with fewer real negatives than the group size are skipped (in the current release: rat, yeast), so worms, flies and mice dominate.

## 6. Method v2 on the same groups (2026-10-20)

`ALLOW_PAID=1 python -m hyparena.negatives v2 --out-dir runs/neg_v2` (cards, verifier with evidence as of the day before the finding, rules, aggregation under `evidence_first`; `hyparena.card.pipeline.as_ladder_result` turns the result into one score: known result > ranked by expected value > not admitted > filtered). About 160 model calls for groups 1–5. Group 6 did not complete (the API quota ran out during it), so the comparison is over groups 1–5. The DrugAge rule for "shortens" and "no effect" claims was added after the run and applied with `v2-refresh` (no model calls).

| Arm (groups 1–5) | hit@1 | MRR | mean rank | AUC [95% CI] |
|---|---|---|---|---|
| chance | 0.10 | 0.29 | 5.5 | 0.50 |
| one call, gpt-5-nano | 0.20 | 0.40 | 3.8 | 0.69 [0.47, 0.87] |
| one call, Gemini flash-lite | 0.40 | 0.54 | 3.6 | 0.71 [0.40, 0.96] |
| L0 (Co-Scientist-style tournament) | 0.20 | 0.34 | 5.6 | 0.49 [0.20, 0.78] |
| L4 (tournament, full) | 0.60 | 0.65 | 4.2 | 0.64 [0.24, 1.00] |
| v2 (cards and rules) | 0.40 | 0.54 | 3.6 | 0.71 [0.40, 0.96] |

**Rank of the finding per group** (L4 / one call Gemini / v2): vitamin D3 in worms 10 / 9 / 3; black tea extract in flies 8 / 4 / 1; 17-α-estradiol in mice 1 / 1 / 9; ethosuximide in worms 1 / 3 / 1; carnosine in flies 1 / 1 / 4. v2 and the LLM judges fail on different groups: v2 does better on the two little-known findings, the judges on the well-known one, which fits the warning that judges may remember findings.

**What decided v2's order.** With evidence cut the day before the finding, the finding itself is unverified in every group (42 of 50 items are unverified). Only in group 2 did evidence decide: a 1971 DrugAge paper refutes the three procaine statements (with the new rule also "procaine shortens lifespan"), and the finding comes first among the rest. In groups 1 and 4 every item is unverified, so the order there comes from indicators without evidence (clinical phase, novelty) and from the draws of unknowns: noise, not skill. v2 abstains where nothing is known, by design; this test rewards a guess.

**Errors found (group 3, mice):**
- "Lovaza shortens lifespan in mice" became supported by a quote that says Lovaza extends lifespan: gpt-5-nano gave the record the wrong stance. Proposed fix: for lifespan claims the verifier extracts only the direction of the effect (increase, decrease, none) and code sets the stance, as for DrugAge.
- "Lovaza extends lifespan in mice", a real negative of the test (no significant effect in DrugAge), is supported by PMID 23918873: "4% Lovaza significantly extends both the median and maximal life span of (NZBxNZW)F1 mice", a lupus-prone, short-lived strain. The claim names no strain, so the finding matches by the rules; the test's label and the verifier both miss that the strain is a disease model. Proposed fix: a disease-model or short-lived-strain flag on records.
- The mechanism variant ("... by activating SIRT1") inherits the supported outcome and becomes a known result; its mechanism stays unverified. This follows the specification.

# Comparing our ranking with a Co-Scientist-style baseline

Status: protocol and tooling are ready; nothing here has been run on real models.

**Beta decision (2026-10-14): memorization is not handled yet.** For the beta, the existing ITP pool (T = 2010-12-31) is used as it is, without the leakage probe and without waiting for a post-cutoff slice. Consequence: the judges may remember ITP outcomes, so absolute numbers are an upper bound, and a difference between arms can partly reflect how well each arm draws on what the model remembers rather than how well it judges. The leakage probe and the fresh slice (sections 2 and 6) stay in place for the later, stricter comparison.

## 1. The claim under test

"From a given pool of hypotheses, our selector ranks the ones that were later confirmed higher than a Co-Scientist-style selector does, at the same cost." It is not a claim about Co-Scientist as a whole: generation and evolution are not compared, and Google's system itself is not available. The baseline is our reimplementation of its ranking (`docs/architecture.md`, section 8b).

## 2. Data and labels

- **Pool:** hypotheses with a known outcome that the judge models cannot know. Current tooling: the ITP pool (`hyparena.backtest build-itp --as-of T`). For a fair comparison T must be after the training cutoff of every judge model (the "fresh slice", accumulated over time).
- **Labels** live in a separate file the pipeline never reads; metrics are computed outside the graph.
- **Splits:** each labelled item is `dev` (tuning prompts, weights, thresholds) or `test` (the one final comparison), stratified by label and deterministic. For the ITP pool with T = 2010-12-31: 5 positives and 18 negatives in dev, 5 and 19 in test.
- **Leakage probe:** `hyparena.leakage` asks each judge model whether it knows the outcome of each item; an item a model names correctly with confidence ≥ 0.6 is "known" and is excluded (`--exclude-known`). Cost: one call per item and model, once per pool.

## 3. Arms: the ablation ladder

Same upstream stages (normalization, retrieval, reviews) for every arm; only the ranking changes, one element per step (`hyparena/ladder.py`, `live run --ladder Lk`):

| Step | Change | Families | Verdict | Rating and pairing | Judge sees |
|---|---|---|---|---|---|
| L0 | Co-Scientist baseline | one | holistic (`criteria-coscientist.yaml`) | Elo from 1200; new, top and similar first | text and reviews |
| L1 | + verdicts per criterion | one | per criterion | as L0 | as L0 |
| L2 | + Bradley–Terry with intervals, elimination pairing | one | per criterion | BT; elimination + Swiss | as L0 |
| L3 | + card and retrieved evidence | one | per criterion | as L2 | text, card, evidence, reviews |
| L4 | full method: + independent judge ensemble | all | per criterion | as L2 | as L3 |

The main comparison is L4 against L0; the steps in between show which change produces a difference.

## 4. Equalizing conditions

- **Budget.** Arms are compared at the same token budget (`--max-tokens`), ideally at 3–4 budget levels (a quality-versus-budget curve). The tournament stops scheduling matches once the budget is spent; in a fake-LLM check a 160k budget ended at 177k (matches already in flight finish). The first cycle's upstream stages are a fixed cost shared by all arms, so `compare` reports both total and ranking-only spend. In the same check, L4 spent about 5× more on judging than L0 per run, which is why equal match counts would be unfair.
- **Model strength.** L0–L3 use one family. To keep a stronger or weaker model from deciding the result, run the single-family steps once per family in the pool and report both the best and the mean.
- **Randomness.** At least 3 seeds per arm (`--seed`); the seed fixes pairing and judge assignment, not model sampling.

## 5. Metrics

| Metric | Meaning |
|---|---|
| AUC of the combined score | probability that a confirmed hypothesis is ranked above an unconfirmed one; main metric |
| AUC per criterion | which criteria carry the signal (and whether judged novelty is misleading, as HindSight suggests) |
| Precision in the top quarter vs the base rate | what a scientist would see |
| Status of positives and negatives | confirmed hypotheses lost before the tournament (rejected by review) |
| Rank stability across seeds (Kendall τ) | reliability of the ranking |
| Spend (total and ranking-only) | cost of the quality |

Unrated items (rejected, merged, never compared) are placed at the bottom by default (`--unrated bottom`), because a rejection is a ranking decision; `--unrated drop` is available for a sensitivity check.

**Statistics:** paired bootstrap over items (stratified by label) of the difference in seed-averaged AUC, with a 95% interval and the share of bootstrap samples above zero. With 5 positives in the test split the interval will be wide; that is a property of the data, to be reported, not hidden.

## 6. Commands

```bash
# 1. pool and labels (dates from PubMed); later: a post-cutoff fresh slice
python -m hyparena.backtest build-itp --as-of <T>
# 2. leakage probe (one call per item and model)
python -m hyparena.leakage --pool data/backtest/itp_<T>.json --labels data/backtest/itp_<T>_labels.json \
    --config configs/paid-test.yaml --out data/backtest/itp_<T>_known.json
# 3. the grid (prints commands; --execute runs them, resumable)
python -m hyparena.experiment --pool data/backtest/itp_<T>.json --as-of <T> \
    --steps L0,L1,L2,L3,L4 --seeds 0,1,2 --budgets 200000,400000 --out-dir runs/exp
# 4. tune on dev, then compare once on test
python -m hyparena.backtest compare --labels data/backtest/itp_<T>_labels.json --split test \
    --exclude-known data/backtest/itp_<T>_known.json \
    --a "runs/exp/L4_b200000_s*.json" --b "runs/exp/L0_b200000_s*.json"
```

`--fake` on `live`, `experiment` and `leakage` runs the whole machinery with the fake LLM at no cost; all of the above was checked that way (the numbers are then random).

## 7. Complementary test: negative sampling

A confirmed finding hidden among nine plausible false statements (real DrugAge negatives and verified synthetic ones), one tournament per group, the same ladder steps as arms: `docs/negative-sampling.md`. It measures telling true from false rather than prioritising open hypotheses, but has far more labelled items than the ITP pool.

## 8. Known limits

- The baseline follows the paper's description, not its code; differences: JSON verdicts instead of "better idea: 1 or 2", K = 32 for Elo (the paper does not give K), our reviews instead of its full set of review types.
- Token counts are estimates (4 characters per token) and exclude hidden reasoning tokens.
- A run stopped by the call cap writes no result unless a checkpoint is used; resume it with `--checkpoint ... --resume`.
- The ITP label is coarse: a significant increase of average lifespan in any ITP row.
- With the current models, the ITP pool before 2020 is very likely contaminated; the leakage probe reduces but does not remove this (a model may know an outcome without stating it confidently).

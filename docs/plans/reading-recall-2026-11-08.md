# Recall of the literature: where papers are lost (plan, 2026-11-08)

Status: plan for the user's review; diagnostics done (free), no paid step run.

## What the outside checks showed

| Check | What we have of the outside reader's papers |
|---|---|
| Argon's graph, 15 calibration trials (2026-11-07) | 47 of 128 link-paper pairs |
| Novelty, pack 7 | 54 of 175 papers that set the level (31%) |
| Evidence balance, pack 8 | 88 of 474 key papers on the right link (19%) |

## Where they are lost (pack 8, 474 key papers)

| Stage | Papers | Share |
|---|---|---|
| never retrieved by the search | 23 | 5% |
| retrieved, but read only for another link of the same trial | 216 | 46% |
| read for this link, no record extracted | 147 | 31% |
| a record on this link | 88 | 19% |

The search is not the bottleneck. Two reading steps are:

1. **Allocation.** Each link reads only the papers its own search returned. A trial of resistance training on muscle power
   finds the key RCT while searching the outcome link and never reads it for the engagement or pathway link it also informs.
2. **Reader recall.** Of the papers read for a link, the reader keeps a minority (the verifier's relevance recall was 0.56
   on the gold of 2026-11-05); the split-reader pilot also drops many records as other interventions.

## Steps

1. **Cross-link reading (code, then paid).** Each link of a chain reads the union of the papers retrieved for every link of
   that trial (deduplicated, date-guarded), capped by a per-link limit chosen from the token cost. Free first: count the
   union per link and the tokens; then a pilot on the 30 prospective trials with the most Argon key papers, priced before
   the run (expected 2-3x the reading tokens of a link).
2. **Reader recall on the papers it reads.** Measure, on the 147 "read, no record" papers, why: stance "neither", quote not
   verbatim, design or population filtered by code, or the relevance answer. Free (the saved replies). Then decide between
   the relevance second question (relevance_check/v1, tested 2026-11-05), the split reader, or a stronger reader for the
   first pass.
3. **Re-check on the references.** R2, R3, and the agreement with packs 7 and 8 (link Spearman, recall of key papers),
   under the 0.03 rule, with two readings averaged where reader noise matters (Spearman 0.81 between two readings).
4. **Search only after that:** the 5% never retrieved do not justify a new search strategy now.

## Questions for the user

1. Cross-link reading raises the reading cost about 2-3x per trial. Pilot on 30 trials first (price before the run)?
2. Should the split reader (Gemini re-labels the context; κ 0.40 vs 0.13) be run on both pools now (about 1.8 USD) and
   checked on R2 / R3, or wait until cross-link reading is settled, since both change the records?

## Diagnostics (free, done 2026-11-08; `scripts/reading_recall.py` -> calibration/reading_recall.json)

**Why papers read for their own link leave no record** (169 key papers of pack 8):

| Reason | Papers |
|---|---|
| not mentioned in the reader's reply at all | 109 (64%) |
| returned as background or speculation, not a finding | 22 |
| read, stance "neither" | 20 |
| in the reply, dropped by code (quote not verbatim, invalid fields) | 17 |
| refused by code (endpoint mismatch) | 1 |

The main loss is silent: with about 20 abstracts in one call, the reader reports some and skips the rest. Reading more papers
per call (cross-link reading) would make this worse, so the two fixes go together: more papers per link, fewer per call.

**Where the "read for another link" papers come from** (216): another chain link's search 152, only an alternative's or an
analog probe's search 64. The union of the chain searches catches 70% of them.

**Reading volume** (DeepSeek V4.1 Flash, off-peak, about 600-670 tokens per paper):

| Pool | Links | Papers per link now | Union of chain searches | Union of all searches | USD now / chain union / all |
|---|---|---|---|---|---|
| prospective | 150 | 19.5 | 48.7 | 119.5 | 0.33 / 0.82 / 2.02 |
| calibration | 177 | 19.2 | 48.9 | 112.5 | 0.34 / 0.87 / 2.01 |

Batches of at most 10 papers per call repeat the prompt (about 2 k tokens) about 5 times per link: about +0.25 USD per pool.

## Proposed pilot (paid, price before the run)

- 30 prospective trials with the most key papers of pack 8; every chain link reads the union of the chain searches of its
  trial, in batches of at most 10 papers (prompt verify_claim/v9, DeepSeek); then the split reader re-labels the context.
- Measures: recall of pack 8 key papers on the right link (now 19%), the share silently skipped, link and trial Spearman
  with pack 8 (now 0.24 / 0.39), records per link; the same on the 30 trials without batching as a control is not run
  (cost); the reader noise (Spearman 0.81) is the yardstick.
- Price: about 0.5 USD for the reading and about 0.4 USD for the split reader, about 0.9 USD in all.
- Then, if it helps, both pools in full (about 2.5-3 USD) and R2 / R3 under the 0.03 rule, the two changes checked together.

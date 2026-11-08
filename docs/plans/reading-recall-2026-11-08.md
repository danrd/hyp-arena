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

# Method v3: earlier versions (v3.0-v3.6)

Removed from the [manual](../method-v3-manual.md) on 2026-11-11 so that the manual describes only the current rules (v3.7).
The text is kept as it was. The worked examples below are still computed and checked by `tests/test_manual.py`.

## Version note of the manual before the 2026-11-11 clean-up

Version: rules **v3.7** as of 2026-11-09 = v3.6 with a slot that has no record left out of the evidence balance and the
support share (`rules_v32.EMPTY_SLOTS = "skip"`, specs/empty-slots-2026-11-09.yaml; section 7), and non-refutation P no
longer shown in the report (it left the profiles in v3.5; the gate still filters refuted chains). v3.6 as of 2026-11-08 (`evaluate(..., v36=True)`, specs/record-weight-2026-11-08.yaml): the record
weight rebuilt on the GRADE domains with fewer levels, and records for and against folded as a sum of log likelihood ratios
(sections 5, 5a, 6); the signed axis is named the **evidence balance** (`chain_state` in the code). v3.5 as of 2026-11-08 (v3.4 + one signed axis in the profiles and a null record weighted
by the power of its study, `evaluate(..., v35=True)`, specs/link-scoring-2026-11-08.yaml); v3.4 as of 2026-11-07 (`hyparena/card/rules_v32.py`, `evaluate(..., v34=True)`; novelty, leverage and the
evolution drift flag in `hyparena/card/novelty_v34.py`; definitions in `specs/v34-frontier-2026-11-07.yaml`), on top of
`rules_v3.py` variant v3.1 and `v3_levels.py`, aggregation by ASPID over the axes (`hyparena/card/aspid_v3.py`, `configs/profiles_v3.yaml`). v3.3
(`evaluate(..., fold=True, neutral_unverified=True)`) differs only in P (section 7) and in two record weights (section 5). The
specification with its history and decisions is `docs/archive/spec/method-v3.md` (in Russian, sections 9-13); this manual is the
self-contained English description. The constants in section 14 and the numbers of the worked example in section 13 are
checked against the code by `tests/test_manual.py`: if the code changes, the test fails until this manual is updated. The
discrete levels of v3 and v3.1, used by earlier runs and still shown as labels, are in appendix A.

## Section 1 axes table and aggregation note (v3.4, with P, support share and V)

| Axis | Question | Range |
|---|---|---|
| P, non-refutation (named plausibility until v3.3) | How far is the chain not refuted by the literature before the date T? | 0-1, product over links (v3.4) |
| support share | How much of the chain is supported by that literature? | 0-1 |
| N, novelty | How far is the hypothesis from what was already asked before T? | new context < translation < analog < new combination < new link |
| I, informativeness | Which supported competing explanations does the stated experiment cut off? | 0-1 |
| W, scope | How far does the supported mechanism reach: one condition, an organ or system, a hallmark of ageing? | local, organ, hallmark |
| V, reference | P × I (0 if filtered): the point of equal weights | 0-1 |

**ASPID** (section 8) is the main aggregation: each profile orders the indicators (P, I, scope, feasibility and others) by
importance, weights are drawn at random under that order, and a hypothesis gets an expected value and the probability of
being in the top. A near-zero P is not compensated (P and I are on log scales). V is reported as one reference point, not
as the ranking.

Only P is meant to track trial outcomes; I, W and V describe what a result would teach, whatever it is; novelty N says how far
the question is from what was already asked. Validation status is in section 12.

## Section 5: the weight table of v3.2-v3.5, the fold and the v3.4 changes

The fold by independence group is unchanged (the heaviest record of a group fully, the others 1/4). The table below
(v3.2-v3.5) is kept for earlier runs.

| Factor | Levels (v3.2–v3.4) | |
|---|---|---|
| design, claim about humans (outcome link) | cells, animal, observational, review, non-randomised, meta-analysis, RCT | 1/7 … 7/7 |
| design, every link before the outcome, or a claim about animals | cells, review, primary study | 1/3, 2/3, 1 |
| precision | outcome link: min(1, ln n / ln 300), at least 1/4, unknown n = 1/4; links before the outcome: 1/2 (v3.4) | continuous |
| effect | where the phrase gives a ratio or a standardised difference: d = abs(ln ratio) × √3 / π or abs(d), weight 1/4 + 3/4 × min(1, d / 0.8); otherwise the rule-A class: none, small, medium, large = 1/4 … 4/4, unclear 1/2 | continuous or class |
| comparison | none, within group, between groups | 1/3, 2/3, 1 |
| context | same class of intervention, adjacent population or species, exact (v3.4: another species alone is not adjacent on the outcome link of a human claim) | 1/3, 2/3, 1 |

A record against (a null or opposite result from a comparison) takes the top effect weight: a clear null weighs like a
clear positive. A record about another intervention altogether weighs 0. Retracted papers weigh 0.

**Folding by independence group.** On each side (for, against) the records of one group are folded: the heaviest counts
fully, every further record of the group with 1/4. F and A are the folded sums.

The distance to the clinic is charged once: links before the outcome use the preclinical design scale, the outcome link the
clinical one. **v3.4** (`specs/v34-frontier-2026-11-07.yaml`, after an outside review):

- on the outcome link of a claim about humans, another species is charged by the design scale only (an animal study 2/7), no
  longer also by the context factor; another population, age, sex, dose or comparator still makes the record adjacent (2/3).
  On the links before the outcome the preclinical design scale does not see the species, so the context factor charges it
  there, once;
- on the links before the outcome precision is a constant 1/2: replicates of cells or animals are not comparable with trial
  participants and are rarely stated in an abstract. Under v3.3 a cell study without n weighed 1/3 × 1/4 = 0.083 and a new
  link needed about eight of them to reach moderate support; now it weighs 1/6.

## Section 6: the Beta strength of v3.2-v3.5, its reading table, the labels and the reference points of v3.4

**Strength, v3.2-v3.5:** S = (cF + 1) / (c(F + A) + 2), the mean of Beta(1 + cF, 1 + cA), with c = 4 / 0.6, so that F = 0.6 with
nothing against gives 5/6 (the old "moderate"). Its 90% interval comes from the Beta quantiles. Reading S:

| Situation | S | Interval |
|---|---|---|
| no record | 0.5; in P the link counts as 1 (nothing refutes it) | wide (0.05-0.95): nothing is known |
| for and against about equal | about 0.5 | narrow: data conflict |
| F = 0.6, nothing against | 0.83 | |
| F = 1.5, nothing against | 0.92 | |
| only against | below 0.5 | |

A label is still shown for reading (appendix A: unverified, weak, moderate, strong, contested, refuted).

Reference points for F: one RCT with ≥ 300 participants, a large between-group effect and the exact population weighs 1.0;
one RCT of 120 with a medium effect about 0.63; a mouse study of 40 with a large effect, between groups, in another species
(context 2/3) about 0.43 on a link before the outcome.

## Section 7: P (non-refutation), the support share and why they changed

- **P** (v3.4; not in any profile since v3.5, not shown in the report since v3.7; kept for the gate and the history) = **non-refutation**: the product over the links of R = (1 + cF) / (1 + cF + cA). R = 1 when nothing is
  against, whatever the support; data against lower it, data for soften that (F = A = 0.6 gives 0.5). Parallel outcomes
  (mass, strength, function) count once: the one matching the primary outcome of the stated experiment, else their mean.
  Consecutive pathway links (a cascade written as several steps) are one slot, their geometric mean. No interval is
  reported: the uncertainty of the support is in the support share. Why: under v3.3 (P = product of S over the links with a
  record, a link without one counting 1) a first modest paper for a new link lowered P from 1 to its S (about 0.6), so the
  first evidence for a new link was a penalty; and P's signal against trial outcomes came from data against anyway. On the
  calibration P v3.4 orders the trials as v3.3 did (AUC 0.584 vs 0.589, 72 units, exploration). For two thirds of the
  hypotheses nothing is against, P = 1, and the order among them comes from the other indicators.
- **Support share** = the mean over the chain's slots (a cascade = one slot, its best link; parallel outcomes = one slot)
  of a = max(0, 2 (S − 0.5)): 0 for a slot without data or with data only against, 2/3 for moderate support (S 5/6), near 1
  for strong support. It carries what P leaves out: a chain of guesses has a high P only because nothing is known, and a low
  support share says so. An ASPID indicator (section 8), right below P in the evidence profile. It replaced a 0/1 share of
  checked slots before any score was used (that one moved with P, |ρ| 0.74, and two thirds of the chains have one slot).
  Consequence (v3.4): finding support for an unchecked link leaves P at 1 and raises the support share; under every profile
  the hypothesis's score goes up (section 13).
- Why (specs/error-analysis-2026-11-06.yaml): under v3.2 a link without data multiplied P by 0.5, so a hypothesis that
  wrote out its mechanism lost a factor of 2 per unchecked link; on the calibration P then ordered the 18 hypotheses with a
  mechanism backwards. The signal of P against trial outcomes came from data against, not from support.

## Section 7: V and headroom I (v3.4 wording)

- **V** = P × I (0 if filtered). **Headroom I** = I if the experiment cut off every supported alternative (d = 1): what
  improving the experiment could add.

## Section 8: profile orders of v3.4 and before

Earlier orders (v3.4 and before): evidence P > support share > I > W > {…}; funding P > feasibility > {trend, AI role,
novelty} > {I, support share} > {…}; frontier trial-1 N > {leverage, W_potential} > P > {I, feasibility}.

## Section 8: v3.5, one axis instead of P and the support share

**v3.5 (2026-11-08): one axis instead of P and the support share.** The **evidence balance** (named "chain state" until
v3.6; `chain_state` in the code) = the mean over the chain's slots
of 2S − 1, from −1 (data against the links) through 0 (nothing known, or for and against balanced) to +1 (supported). It
replaces P and the support share in every profile: evidence = chain state > I > W > {best design, independent sources,
endpoint}; funding = chain state > feasibility > {trend, AI role, novelty} > I > {W, endpoint, best design, independent
sources}; frontier = novelty > chain state > {I, feasibility}. Why: the support share gave 0 both to a refuted link and to an
unknown one; P told them apart but was 1 for two thirds of the hypotheses. The chain state orders the calibration trials
as P does (AUC 0.597-0.609 vs 0.595) and separates far better (its most common value covers 33% of hypotheses, P's 67%).
It is linear, so a refuted chain is compensated a little more than under P's log scale; strong refutation is still
filtered by the gate. **A null record weighs by the power of its study** to detect d = 0.4 (two-sided 5%; between groups
Φ(0.4·√(n/4) − 1.96), before-after Φ(0.4·√n − 1.96), n unknown → 40), replacing its precision and effect factors: a null
of 20 people weighs little, a null of 300 fully. P and the support share are still computed and shown. On the prospective
pool the rankings move moderately (Spearman 0.88-0.95 with v3.4, 7-9 of the top 10 kept).

## Section 10: the first report layout

**Pool report, first layout** (`python -m hyparena.report_html prospective --n 60`; one HTML page, built by code with fixed wording,
Russian and English in one page; layout redone 2026-11-07 after the structure of an outside reader's report). A header band
(method, cut-off date, how many scored) and five tabs:

1. *Ranking*: one sub-tab per profile; the table shows the place, the expected score, the probability of the top 5, the room
   to improve (section 11; `*` when "write the mechanism" could not be computed, `↓` when the improvements would lower
   novelty) and the profile's indicators in its order of importance (the reader chooses the columns): P in red when below 1,
   novelty with the PMID of the record that sets it, I with its headroom. Pages of 15 rows, search, filter by intervention
   type. Improved versions are ranked with the rest as their own rows, marked "tuned version" or "free evolution" (+ "new
   hypothesis after"). No separate top-3 block.
2. *Hypotheses* (collapsed, one-line verdict; open all / close all): the chain with each link coloured by S; P, novelty, I,
   support share, scope, endpoint, AI role, places; what lifts and what lowers it; **the table of links**: F / A, S with its
   90% interval, R, the link's novelty level, the records as chips with their weights (green for, red against; hovering a
   chip shows the design, n, weight and the verbatim quote, a click opens PubMed); the stated experiment; the alternatives
   with what the experiment does to each; the room to improve and the improvement list (collapsed).
3. *Evolution* (when run): section 11; the summary table first (mode and items, P, I, support share, novelty with the drift
   flag, the score under each profile), the details of each pair collapsed after it.
4. *Sources*: every record of the pool, one row per paper and link (PMID, hypothesis, link, for or against, design, n,
   weight, quote), with search and sorting.
5. *Help*: how to read the report, ASPID in brief, **a glossary of every parameter** (the same texts as the hover notes),
   provenance and limitations.

Every column header, chip and indicator name has a hover note; the notes float above the table (they are not clipped by it
and do not cover other notes).

## Section 11: the room to improve on the prospective pool under v3.4

On the prospective pool (55 ranked trials): a positive room for 50 (evidence), 51
(funding) and 45 (frontier); median +0.10, +0.04 and +0.06, largest +0.30, +0.22 and +0.64 (frontier: a refuted link
rewritten lifts P from low to 1, and P is its second tier). The commonest item is the experiment that rules out the
alternatives (42 hypotheses), then the endpoint (23) and a refuted link (14). The top 10 by room share 9 hypotheses between
evidence and frontier: on registry trials the room comes mostly from the same fixes, whatever the profile. Novelty would
change for one.

## Section 11: the first evolution run (2026-11-06)

**First run** (2026-11-06, `specs/evolution-v3-pilot-2026-11-06.yaml`): the top 10 of the pilot under the evidence
profile; about 311 calls (about 0.8 USD). The score under the evidence profile rose for 2 and fell for 8 (down to −0.17),
against an expected +0.04 … +0.11. The reason is the design of the mode, not the hypotheses: (1) the whole pipeline ran
again, so a new card, a new search and new alternatives changed everything at once (I fell for 3, because the alternatives
were proposed anew, not the same ones); (2) the prompt's layout asked for a mechanism line every time, so every version
wrote out a mechanism, the chains grew by 2 to 7 links, the new links were checked and often found weak or contested, and P
fell in 9 of 10 (e.g. 0.93 → 0.26). The useful side: writing the mechanism out shows the links a hypothesis rated well on its
outcome alone actually rests on. The controlled and free modes above answer the two flaws.

## Section 12: P limit

- P (v3.4, now named non-refutation) is 1 for about two thirds of registry hypotheses: it says "nothing refutes it" and
  nothing more (whether to keep it as a separate indicator is open, user 2026-11-07); the order among
  them comes from the support share, I and the other indicators of the profile.

## Section 12: validation status of 2026-11-07, the ablation and the ceiling of the label

**Validation status (2026-11-07).**

| Check | Result |
|---|---|
| extraction of design, comparison, n (three hand-labelled sets) | passed each time (0.81-0.96) |
| effect class (rule A) | passed formally (most effects "unclear") |
| P vs trial outcome, calibration (30 trials, seen while building v3) | v3 0.677, "unclear"; v3.2 0.65 |
| P vs trial outcome, fresh sample 2023-2026 (14 decisive) | v3 0.571 "unclear"; v3.2 0.61 (not pre-registered) |
| P vs trial outcome, fresh sample 2000-2022 (26 decisive) | v3 0.534 "no signal"; v3.2 0.64 (not pre-registered) |
| evolution, first run (pilot top 10) | scores fell for 8 of 10: the mode re-ran the whole pipeline and forced a mechanism; see section 11 |
| error analysis on the calibration (exploration) | P's signal comes from data against the outcome (AUC 0.63), support does not separate; unchecked links penalised written mechanisms → v3.3 (0.66 on the same data, not a test) |
| prospective pool: 60 ongoing trials ending 2026-11 … 2028-12 | scores frozen 2026-11-06 with a SHA-256 (`specs/prospective-2026-11-06.yaml`); the clean test of v3.2, when the trials report; v3.4 scores in `scores_60_v34.json` (the frozen file is not rewritten) |
| error analysis, 74 units rerun (normalize v10) under v3.3 | P 0.60, support share 0.54, the outcome link alone 0.61; with a written mechanism P is at chance (0.46, 17 units) |
| v3.4 (P non-refutation, two weight changes) | P 0.584 vs v3.3 0.589 on the same 72 calibration units: the same order, the paradox removed (exploration) |
| novelty, leverage, frontier profile | cannot be checked against trial outcomes; they rest on the admission rule and the protections above |

**Ablation on the calibration** (`scripts/ablation.py`, 73 units, exploration; one standard error of an AUC here is about
0.065, so only large changes mean anything):

| What is removed | AUC |
|---|---|
| nothing: P v3.4 / P v3.3 | 0.595 / 0.600 |
| any one factor of the record weight (design, precision, effect, comparison, context) | 0.595–0.598 |
| every factor: each record weighs 1 (P counts records only) | 0.602 |
| P replaced by the outcome link alone | 0.614 (without design 0.622) |
| support share alone | 0.540 |
| ASPID score, evidence profile: all / without P / without I | 0.543 / 0.491 / 0.559 |
| funding profile: all / without P / without I / without trend | 0.583 / 0.552 / 0.632 / 0.606 |
| frontier profile: all / without P / without N | 0.553 / 0.502 / 0.588 |

Reading: against trial outcomes the record-weight machinery carries no signal (counting records does as well); P's signal is
whether there are data against, mostly on the outcome link; I is inversely related to a positive result (informative
experiments test open questions and are more often null); only P is meant to track outcomes, so the other indicators of a
profile dilute this AUC by design. The weights stay for what they are for (telling a large RCT from a cell study in the
report), not because they improve the outcome AUC.

**Ceiling of the label** (`scripts/ceiling.py`): the design of the trial (randomisation, blinding, placebo or sham, sponsor,
endpoint, number of primary outcomes; from ClinicalTrials.gov) does not predict the outcome either (cross-validated 0.51).
Open and sham-free trials are positive far more often (63% vs 38% for blinded): there "positive" partly measures room for bias.
Within placebo- or sham-controlled trials the outcome link reaches 0.75 (n 20, very uncertain). The benchmark analysis
should therefore be stratified by blinding and placebo, or take the blinded subset as primary.

AUC is the tied AUC of P between positive and null trials; the pre-set rule is "signal" at ≥ 0.60 with the lower bound of
the 95% interval above 0.45, "no signal" below 0.55. The samples are small and the intervals wide.

## Section 13: the worked example under v3.3, v3.4 and v3.6

| | c1 engagement | c2 pathway | c3 outcome | P [90%] | support share | I | W | V |
|---|---|---|---|---|---|---|---|---|
| v3.3 | S 0.906 (F 1.293) | no record, not in P | S 0.839 (F 0.63) | 0.760 [0.412; 0.985] | 0.496 | 0.651 | organ | 0.494 |
| with one mouse study of 40 for c2 | | S 0.842 | | 0.639 | 0.724 | | organ | 0.416 |
| with one mouse study of 40 against c2 | | S 0.158 | | 0.120 | 0.496 | | | |

| v3.4 | S 0.885 (F 1.000) | no record, R 1 | S 0.839 (F 0.63) | 1.000 | 0.482 | 0.476 | organ | 0.476 |
| v3.4, with one mouse study of 40 for c2 | | S 0.812 | | 1.000 | 0.691 | | organ | 0.476 |
| v3.4, with one mouse study of 40 against c2 | | S 0.188 | | 0.231 | 0.482 | | | |

| v3.6 | S 0.936 (F 1.000) | no record | S 0.905 (F 0.839) | evidence balance 0.560 | | 0.581 | organ | |
| v3.6, with one mouse study of 40 for c2 | | S 0.793 | | evidence balance 0.756 | | | | |
| v3.6, with one mouse study of 40 against c2 | | S 0.342 | | evidence balance 0.455 | | | | |

## Section 13: reading the example under v3.6, v3.4 and v3.3

Under v3.6 the RCT of 120 with a medium effect weighs 0.839 (its effect counts in full), each link's S comes from F − A,
and a mouse null of 40 weighs by its power (0.24; preclinical design 1, between groups 1) against 0.5 for the
mouse study for, so it lowers the balance less than under v3.5 (0.455 vs 0.333).

Under v3.4 the c1 records weigh more (precision 1/2 before the outcome), P is 1 until something is against, the study for c2
raises only the support share, and the study against c2 cuts P to 0.23. Novelty: new context (an RCT on the outcome exists).
Under v3.3: the study for c2 lowers P slightly and raises the support share; under every profile the expected score rises (evidence
0.667 → 0.703 on these two alone). A study against c2 cuts P to 0.12: data against are what P is for. Under v3.2 the first row had
P 0.380 (c2 at 0.5), the penalty for writing out the mechanism that v3.3 removes.

## Appendix A. Discrete levels of v3 and v3.1

Runs before 2026-11-06 were scored with discrete levels; v3.2 keeps them as labels. F = summed weights for, A = against;
precision in bands (unknown or < 30, 30-99, 100-299, ≥ 300: 1/4 … 4/4) and the effect by class.

| Level | Rule | Weight S (v3) | Weight S (v3.1) |
|---|---|---|---|
| refuted | strong refutation (gate) | 1/6 | 1/6 |
| contested | A > 0 and A ≥ F/2 | 2/6 | 3/6 |
| unverified | no usable record | 3/6 | 2/6 |
| weak | 0 < F < 0.6 | 4/6 | 4/6 |
| moderate | F ≥ 0.6 | 5/6 | 5/6 |
| strong | F ≥ 1.5 and at least two independent sources | 1 | 1 |

In v3 and v3.1, V = P × W × I with W = 1/3, 2/3, 1; in v3.1 the alternative's support a is weak 1/3, moderate 2/3, strong 1.

## Section 10: the report layout of 2026-11-08 (replaced 2026-11-11)

**Pool report, main layout** (`python -m hyparena.report_v2 prospective --n 60` → `report_<n>_v2.html`; user decision
2026-11-07: the outside reader's (Argon's) report taken as the base and corrected towards the method; layout as of 2026-11-08).
The same numbers as below, reshaped by `hyparena/report_v2.py` into one JSON object that the page template
`hyparena/templates/pool_report_v2.html` renders in the browser (Tailwind from its CDN, version pinned). Russian only.

*Content.* Tabs: *Ranking* (profile tabs with the order of importance written out; one fixed table: place; hypothesis with
its status chips — original, tuned version, free evolution, new hypothesis after, moved towards the known —; score; **room to
improve** (one column, with `*` and `↓`; the headroom of I is not a separate column but in the hover note of I); place /
probability of top 5; novelty with the PMID that sets it; **evidence balance** (−1 … +1, red below −0.05, green above
+0.05); I; scope; feasibility, AI role and endpoint one per line; filters by status and intervention type, search, pages of
15; a click opens the card), *Hypothesis cards* (one card per original hypothesis; when it has improved versions, buttons
switch between "comparison", "original only" and "version only"; the two chains side by side; one table of links with rows
"original / version": F / A, S with its interval, R, link novelty, record chips whose hover shows every factor of the weight
and the verbatim quote, a click opens the paper card; what lifts and lowers; the alternatives; the room and the improvement
list), *Evolution* (every pair: mode, the indicators of both versions, novelty with the drift flag, the change of the score under
each profile; a placeholder when the pool has no evolution results; no shortcut button elsewhere), *PubMed papers* (every
paper with its quote and the hypotheses that use it), *Help* (how to read the report, the record weight table of v3.6 with
its GRADE domains, S as a log-likelihood sum, the evidence balance (slots with data, v3.7), the reading rules, novelty, the experiment and
the other indicators, the profiles from the configuration, room and evolution, limits and validation status including the
outside checks (section 12), provenance, and a glossary of every parameter).

*Style* (fixed in the template; change it there): dark green header band (#1E4D40) with the method version badge; serif
titles (Noto Serif), Inter for text; every column header, chip and number has a hover note that floats above the table; one
item per line where a cell holds several (no wrapped "a / b / c"); long headers wrap to two lines instead of widening the
column; the page uses the full window width (up to 1920 px) and a larger base size on desktop (17 px from 1280 px, 18.5 px
from 1680 px, 20 px from 2200 px). Colours carry meaning only for direction (red against, green for, amber for flags).

The first layout (`python -m hyparena.report_html prospective --n 60`, bilingual, 2026-11-07) is kept in the code; its
description is in `archive/method-history.md`.

Reports on private hypotheses stay in the private repository (`longevity-kg`).

**A report written by a model from this manual** (section 0) follows the same order for one hypothesis: summary (evidence balance and
coverage, novelty with the record that sets it, I, scope, places under the three profiles if there is a pool, and the room to improve under each), the chain table
(id, type, claim, S with interval, R, F / A, link novelty level, main records), why (what lifts, what lowers, the
alternatives), what to improve (actions with the score they would give, and the change of novelty they would cost),
limitations, provenance. The older one-hypothesis report by code (`python -m hyparena.analyze`) still uses the v3 / v3.1
levels.

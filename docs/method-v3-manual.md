# Method v3 manual: how a hypothesis is scored and how to read the report

Version: rules **v3.6** as of 2026-11-08 (`evaluate(..., v36=True)`, specs/record-weight-2026-11-08.yaml): the record
weight rebuilt on the GRADE domains with fewer levels, and records for and against folded as a sum of log likelihood ratios
(sections 5, 5a, 6); the signed axis is named the **evidence balance** (`chain_state` in the code). v3.5 as of 2026-11-08 (v3.4 + one signed axis in the profiles and a null record weighted
by the power of its study, `evaluate(..., v35=True)`, specs/link-scoring-2026-11-08.yaml); v3.4 as of 2026-11-07 (`hyparena/card/rules_v32.py`, `evaluate(..., v34=True)`; novelty, leverage and the
evolution drift flag in `hyparena/card/novelty_v34.py`; definitions in `specs/v34-frontier-2026-11-07.yaml`), on top of
`rules_v3.py` variant v3.1 and `v3_levels.py`, aggregation by ASPID over the axes (`hyparena/card/aspid_v3.py`, `configs/profiles_v3.yaml`). v3.3
(`evaluate(..., fold=True, neutral_unverified=True)`) differs only in P (section 7) and in two record weights (section 5). The
specification with its history and decisions is `docs/spec/method-v3.md` (in Russian, sections 9-13); this manual is the
self-contained English description. The constants in section 14 and the numbers of the worked example in section 13 are
checked against the code by `tests/test_manual.py`: if the code changes, the test fails until this manual is updated. The
discrete levels of v3 and v3.1, used by earlier runs and still shown as labels, are in appendix A.

## 0. Using this manual as context

Attach this manual to a hypothesis (and, if available, the literature found for it) and ask for a report in the template of
section 10. Rules for a model writing such a report:

- Score only what the literature you were given says; every record needs a PMID and a verbatim quote. A record you cannot
  quote does not exist.
- Use the scales and formulas of sections 5-7 exactly; show the arithmetic for P, the support share, I and V, and the record
  that sets the novelty level.
- Do not predict the outcome of the trial; P is non-refutation of the mechanism given the literature, not a forecast.
- When in doubt between two levels, take the lower one and say why. For novelty, take the level nearer the known: a paper you
  were not given may exist, and missing data are never novelty.
- A report written this way is an approximation. The authoritative report is the one the code builds
  (`python -m hyparena.analyze RUN.json`), from the same rules and the records the verifier extracted.

## 1. What is evaluated

A hypothesis is valued for its **mechanism**: a chain of links from the intervention to the outcome. A hypothesis is
promising when the key links are not refuted by current data and the mechanism, if true, would change the question a lot.

The method computes **axes** (what can be checked against the literature) and then ranks hypotheses by **ASPID** under
several **profiles** (whose order of importance says what matters to whoever ranks):

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

## 2. Inputs

- The hypothesis text as written (a registry entry, a grant proposal, a pitch).
- The date T: only papers public on or before T count (the evaluation is "as of T").
- For registry hypotheses, the registry fields (population, design, control, planned n, primary outcome).

## 3. The card

A model (the normaliser) turns the text into a card:

- **Claims** with roles, and for the mechanism a **link** type: `delivery` (the intervention is given and reaches the tissue),
  `engagement` (it acts on its target), `pathway` (the target changes a pathway), `effect` (an intermediate effect),
  `outcome` (the clinical or functional outcome). If the text argues a mechanism, the chain must be written; a missing link
  is a flag ("build mechanism"), not an error.
- **Hallmarks of ageing** on engagement, pathway and effect links when the link concerns one.
- **Population** (for registries taken from the registry fields).
- **The stated experiment**: design, control, planned n, primary outcome.
- **Alternatives**: competing explanations, proposed by a second model call from the literature found, each with its support.
- **AI role** (normaliser v10): none / AI analyses the data / AI in the experiment loop / AI is the intervention, with a
  verbatim phrase of the text; without one the code sets "none". An indicator of the investor profile only.

## 4. Evidence records

A verifier model reads each abstract found for a claim (PubMed, date-cut, queries written by a model, citation expansion) and
returns records:

- a verbatim quote (checked by code; a quote not in the abstract is dropped);
- stance: supports / refutes / neither (only supports and refutes are scored);
- from the whole abstract: `design` (rct, non_randomised, observational, animal, cells, review, meta_analysis, other),
  `n_total` (only when stated as one number; group sizes are not summed; checked verbatim), `comparison` (between groups,
  within group, none), `effect_reported` (the verbatim phrase with the effect size);
- `effect_class`, computed by code from the effect phrase (rule A):

| Phrase | Small | Medium | Large |
|---|---|---|---|
| ratio (OR, RR, HR, n-fold) | 0.8-1.25 | 1.25-2 or 0.5-0.8 | ≥ 2 or ≤ 0.5 |
| standardised difference (d, g, SMD) | < 0.5 | 0.5-0.8 | ≥ 0.8 |
| percent change ("+12%", "reduced by 35%") | < 5 | 5-20 | > 20 |
| the authors' word | small, modest, slight | moderate | large, substantial, marked |

  Raw units ("+2.4 kg"), test statistics and p values alone are "unclear". A null result for the outcome closest to the claim
  is "none". Since 2026-11-08 the parser also reads a ratio written as "hazard ratio [HR], 0.82", percent changes written
  as "Mean Δ% = 40.4%", "ΔEG/CG: 29.67%" or "increases from baseline of 21%", and a raw difference with its 95% interval
  when n is known: SE = (hi − lo) / 3.92, SD = SE·√n / 2 between two groups (SE·√n before-after), d = |difference| / SD
  (`effect_class.d_from_ci`), used by the record weight and by the experiment forecast.
- A review restating one trial counts as that trial (an RCT of unknown size until the trial's own paper is found).
- **Independence group**: a paper whose abstract names exactly one trial id (NCT, ISRCTN) belongs to that trial; else the
  paper is its own group. Several records of one group count once (section 5).
- Retracted papers weigh nothing (v3.1: also when PubMed itself marks them retracted).

**Reading rules where readers disagree** (added 2026-11-07 after a blind comparison of two readers on the same three trials;
the verifier prompt `verify_claim/v9` already follows them; a report written by a model from this manual must too):

1. **Same intervention or not** (`intervention_match`). *exact*: the intervention the claim names (the same programme, the
   same compound); a different dose or schedule of it is exact with dose or regimen "no", which makes the record adjacent.
   *class*: another intervention of the same kind on the claim's outcome (another resistance programme for a squat
   programme; another drug of the same class) — it counts, with context 1/3. The match is judged at the level at which the
   claim names the intervention (verifier prompt v10, 2026-11-08): when the claim names a kind ("resistance training",
   "adequate protein intake", "a home-based exercise programme"), any study of that kind is exact; class only when the claim
   names a specific product, compound or programme and the study used another member of its kind. A programme that merely includes the named
   intervention among several components (resistance training + nutrition + cognitive training for "squats") is *class*, and
   only when its result can be read for the exercise arm; otherwise it is not a record for this claim. *Another intervention
   altogether* (aerobic training for a resistance claim) weighs 0.
2. **Against means null or opposite, not small.** A record is *against* when the result for the claim's own measure is no
   effect (not significant against control, or no change in a before-after design) or the opposite direction. A significant
   effect judged clinically small (below a minimal important difference) is a record *for* with a small effect (weight 1/4),
   not a record against. A null on another measure of the same study is not against this claim (it may be against another
   link of the chain).
3. **Comparison is read from the analysis behind the sentence, not from the number of arms.** "X did not change in either
   group over 12 weeks" is a within-group (before-after) result, 2/3, even in a two-arm trial; "no difference between groups"
   is between groups, 1.
4. **A null primary outcome with positive secondary ones** gives two records: the null primary against, the secondary for
   with the flag subgroup_only or as a separate measure.
5. **Only what the claim fixes** (2026-11-08, `rules_v32.only_claim_qualifiers`, specs/record-weight-2026-11-08.yaml): a
   record is adjacent only on a qualifier the claim itself states (population, disease or age; sex; dose; comparator;
   species, which a claim about humans always fixes). A study in women for a claim that says nothing about sex is exact. Before
   this rule the verifier's "no" on unstated qualifiers made 53 of 98 adjacent records adjacent; on the references the
   change is neutral.
6. **Population.** A record in the exact population of the trial (pre-sarcopenia for a pre-sarcopenia trial) is exact even
   when it is small; a record in a neighbouring population (sarcopenia, healthy older adults) is adjacent. Search for the exact
   population first: in the comparison the most informative record (a null SPPB result of a resistance programme in
   pre-sarcopenia) was found by one reader and missed by the other.
7. **Numbers a reader cannot compute are left unknown**, not estimated: the trend of attention and the literature counts are
   computed by code (section 8); a model-written report marks them "not computed".

## 5. Weight of a record

`w = design × precision × effect × comparison × context`.

**v3.6 (current, 2026-11-08; `rules_v32.record_weight_v36`).** Each factor is one GRADE domain; why each one and each
level is in section 5a.

| Factor (GRADE domain) | Levels |
|---|---|
| design (starting level), outcome link of a claim about humans | RCT and meta-analysis 1; non-randomised and observational 1/2; review, animal, cells, other 1/4 |
| design, links before the outcome or a claim about animals | cells 1/3, review 2/3, primary study 1 (unchanged) |
| precision (imprecision) | record for: min(1, ln n / ln 300), at least 1/4, n unknown 1/4; before the outcome 1/2. Record against (a null): the power of its study to detect d = 0.4 (v3.5) |
| effect (rating up for a large effect) | record for: a stated effect of at least medium size (d ≥ 0.5, ratio ≥ 1.25, ≥ 5%, the authors' "moderate") 1; small, none or not stated 1/2. Record against: 1 |
| comparison (part of risk of bias) | between groups 1; within group or none 1/2 |
| context (indirectness) | adjacent 1/2 (another population, age, sex, dose, comparator or species, only on qualifiers the claim states); exact and class 1 |

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

## 5a. Why each factor and level (v3.6)

The record weight was checked on 595 records of 133 trials against references other than the noisy trial outcome
(specs/record-weight-2026-11-08.yaml): **R2**, later RCTs and meta-analyses of the same link predicted from the records
published before them (195 targets on 71 links); **R3**, the trial outcomes, as a constraint (not lower than 0.03 below
v3.5); **R4**, the order of 80 pairs of records of one link given by an outside reader (Argon), blind to the weights. The
rule: a simpler variant, or one closer to GRADE, wins unless it is worse by more than 0.03.

- **Design, three levels.** The seven-level scale put a meta-analysis (6/7) below a single RCT; the outside reader put the
  meta-analysis first in all 7 such pairs, as GRADE does. With both at 1, the larger n decides. Most records on the outcome
  link are RCTs, so the finer levels below them separated little.
- **Precision stays continuous.** It sets most of the order of records (42% of the spread of the weights for, 67% for nulls
  through power); three steps by n broke the R3 constraint (0.573).
- **Effect as rating up.** The effect is stated in only one record in five; a full weight for a stated medium or large
  effect, half otherwise, is better than dropping the factor (which lowered both R2 and R3) and than counting "not stated" as
  full (R2 0.693, R3 0.580, R4 0.065 against 0.712, 0.595, 0.099). Not stated counts as small: when in doubt, the lower level.
- **Comparison, two levels.** Between groups or not; the within-group / none distinction added nothing.
- **Context, two levels.** The verifier's "class" label agreed with a hand check at κ 0.38 and with the outside reader at
  κ 0.10 (it calls class about twice as often as either reader), and charging it 1/3 lowered R2; until the verifier is re-run
  with the v10 reading rule, class is not charged. Adjacent is charged once, 1/2, and only on qualifiers the claim states.
- **Not adopted:** risk of bias from abstract words (65% of trial abstracts say nothing about blinding; the
  subjective-outcome word rule was confirmed by the outside reader on 13 of 29 records) — to return when the verifier
  extracts blinding; a penalty for subgroup-only results (broke R3).
- **Fold.** A sum of log likelihood ratios (section 6) beat the Beta mean on R2 (+0.023, the only paired interval of the
  check above 0) and on R3; the best-evidence rule failed R3; counting papers without weights was the lowest on R2 (0.653)
  but the highest on R3 (0.622), so against trial outcomes the weights still add nothing over counting.
- **Overall** (v3.6 against v3.5): R2 0.702 vs 0.657 (paired 95% interval +0.009 to +0.091), R3 0.593 vs 0.608, R4 τ-b 0.099
  vs 0.043; the order of the 186 links moves moderately (Spearman about 0.92). All numbers are in-sample and the intervals
  are wide (R2 about ±0.09): the choice rests on GRADE and clarity, the data show that it is not worse.

## 6. Strength of a link and the gate

F = folded weight of the records for, A = against.

**Strength, v3.6** (current): S = 1 / (1 + exp(−λ(F − A))), λ = 2 atanh(2/3) / 0.6 ≈ 2.68: every record is evidence
with log likelihood ratio λw for the link (for) or −λw (against), and S is the probability after them from even odds.
F = 0.6 with nothing against gives 5/6, as the Beta did; F = A gives 0.5 whatever their size. Unlike the Beta mean, S
depends on the difference F − A, not on the ratio: three units for and one against (S 0.995) count more than one for and
none against (0.936). The 90% interval is still the Beta's: it shows how much data there are, not where the point lies.

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

**Approved action.** An engagement link whose subject is one approved drug (ChEMBL phase 4) with one of its ChEMBL targets
named in the link is taken as at least 5/6 without search.

**Gate (the only filter).** A key link is refuted when there is a record against of the top design (RCT or meta-analysis),
between groups, in the hypothesis's population, and no record for of that level. Then the hypothesis is filtered (V = 0, not
ranked). Nothing else filters: an undeveloped but promising hypothesis keeps its score and gets flags.

## 7. Axes

- **P** (v3.4) = **non-refutation**: the product over the links of R = (1 + cF) / (1 + cF + cA). R = 1 when nothing is
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
- **W, scope**, from supported links only: a hallmark of ageing (needs a link at least moderate), an organ or system, else
  local. A scope that is claimed but not supported counts as local. An indicator of ASPID, not a factor of V. A hallmark is
  the link's own object (a measured hallmark process: senescent cells, proteostasis markers, mitochondrial function), not
  something inferred from the kind of intervention: "protein after exercise → muscle protein synthesis" is an organ link,
  not the hallmark "loss of proteostasis".
- **I** = min(1, Σ a·d / 1.5) over the proposed alternatives, from 0 to 1 (v3.4, 2026-11-08; until then 1/3 + 2/3 × the same,
  a floor of 1/3 kept for the log scale and for V; in ASPID the floor had no effect, so it was dropped, and I is now on a
  linear 0-1 scale). **Headroom I** = the same with d = 1 for every supported alternative. a = support of the alternative, max(0, 2 (S − 0.5))
  with S its strength; d = what the stated experiment does to it at either outcome (cut off 1, weakened 0.5, unchanged 0).
  Without supported alternatives I = 0: an invented alternative adds nothing. **How d is set** (added 2026-11-07): d = 1
  only when the experiment has a named arm, control or measurement for which the hypothesis and the alternative predict
  different results, and one of the possible results contradicts the alternative (an active control matched for attention
  rules out "any attention helps"); d = 0.5 when the experiment only measures the variable the alternative depends on,
  without an arm that separates them; d = 0 otherwise. A design label alone ("factorial 2×2", "double-blind") gives nothing
  until each alternative is named with the arm and the result that would rule it out. **Who sets d** (2026-11-08, `hyparena/card/alternatives_d.py`): until then the model that proposes the alternatives set d
  from the compressed card, without the registry text, and almost never said "eliminated" (2 of 293 on the prospective
  pool); an outside reader agreed with it at κ 0.07. Since 2026-11-08 d is judged by `judge_alternatives/v2` from the
  registry text, writing what the hypothesis and the alternative predict for each named arm, with the separating phrase
  copied verbatim (an "eliminated" without one becomes "weakened"); on a holdout of 30 trials it agrees with the outside
  reader at κ 0.35 (specs/informativeness-check-2026-11-08.yaml). The support a is unchanged: from the records found.
- **V** = P × I (0 if filtered). **Headroom I** = I if the experiment cut off every supported alternative (d = 1): what
  improving the experiment could add.

- **N, novelty** (v3.4, `novelty_v34.novelty`): the distance of the hypothesis to what was already asked before T, from the
  usable records on either side (a question already asked is not new, whatever the answer). On the outcome link, by the
  closest record: **new context** (the same intervention and outcome in the claim's species, another population, age, sex or
  dose), **translation** (the same intervention, only in another species), **analog** (only a related compound or class).
  Without any outcome record: **new combination** (every link before the outcome is supported: the pieces are known, the
  chain as a whole was not tested), **new link** (at least one link before the outcome has no record and at least one is
  supported). **Unknown** when there is no data anywhere or the chain is the outcome alone: absence of evidence is not
  novelty. The exact known result (same intervention, species, sex, age and dose, supported) stays the separate
  "known result" outcome and is not ranked. The same ladder per link (`link_levels`) feeds the evolution flag (section 11).
- **Leverage** (defined, in no profile): how much the support share would rise if the bottleneck slot reached S = 5/6,
  times the mean support of the other slots, so a chain of guesses or one link alone has none. **W potential**: the scope
  with the bottleneck confirmed.

Protections against inflated hypotheses, by construction: the product over links; alternatives without support weigh 0;
scope only from supported links; records of one trial or paper count once; novelty is unknown, not high, without data.

## 8. ASPID: indicators and profiles

Values sit on fixed scales, so a hypothesis's expected value does not depend on the rest of the pool. An unknown value is
drawn over its whole range in every draw.

| Indicator | What it says | Scale |
|---|---|---|
| P | non-refutation of the chain | log, from 0.01 |
| I | informativeness of the stated experiment (headroom I, of an improved one, feeds the room to improve, section 11) | linear, 0-1 |
| W | scope | local < organ < hallmark |
| feasibility | system, duration, planned n, readiness of the intervention (approved or not a compound 1, in trials 0.5, neither 0) | 0-1 |
| best_design_outcome | best design among the records of the outcome link | cells … RCT |
| independent_outcome | independent sources for the outcome link | 0-5 |
| against_share | share of the chain's weight against (in no profile since v3.4: |ρ| 0.87 with P) | 0-1, lower better |
| endpoint_clinical | how close the trial's primary endpoint is to a clinical outcome (two model families agree, else unknown) | biomarker < patient-reported < function < clinical event |
| support_share | how much of the mechanism chain is supported: mean of max(0, 2 (S − 0.5)) over its slots (v3.3) | 0-1 |
| trend_pubmed | rising attention: PubMed records on the intervention in the last 3 years vs the 3 before, net of PubMed's growth | -0.5 … 1.5 |
| ai_role | role of AI in the hypothesis | none < analysis < in the loop < AI is the intervention |
| N | novelty (section 7) | new context < translation < analog < new combination < new link |
| leverage, W_potential, literature_density | defined in code, failed the admission rule on the trial pools (below) | |

| Profile | Order of importance (tiers) |
|---|---|
| evidence | P > support share > I > W > {best design, independent sources, endpoint} |
| funding (merged with the investor draft, 2026-11-06) | P > feasibility > {trend, AI role, novelty} > {I, support share} > {W, endpoint, best design, independent sources} |
| frontier (2026-11-07; exploratory programmes such as ARPA-H, Foresight, early R&D) | novelty > P > {I, feasibility} |

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

There is no separate "room to grow" profile any more (removed 2026-11-07, user decision): what improving a hypothesis would
give is computed under every profile as the **room to improve** (section 11), so the profile duplicated it, and only for one
kind of improvement (a better experiment). Headroom I stays an input of that computation, not an indicator of any profile.

The evidence profile has no novelty on purpose: there novelty and P pull apart by design. The frontier profile has
no support share on purpose: it rewards the known. Its protection against inflated hypotheses is that unknown novelty is
drawn over the whole range (not set high), P falls with any data against, and I counts only supported alternatives.

A new indicator enters only when it passes four conditions, checked on saved data before it is used: reliable (computed by
code, or extracted with a verbatim phrase and agreed by two model families, κ ≥ 0.6); separating (at least three values,
none above 70%); not redundant (|Spearman| < 0.7 with the existing indicators); its own question. Rejected so far:
four-axis indirectness (redundant), estimand completeness (unreliable), genetic support of the target (too few values on
registry trials), trial-registry trend (adds nothing). Checked for v3.4 on 127 units (72 calibration + 55 prospective that pass
the gate, `scripts/v34_check.py`): N passes (five levels, the largest 60%, unknown for 34%, |ρ| ≤ 0.24 with every indicator);
leverage fails (83% zero; in its first form, without the factor for the rest of the chain, it was |ρ| 0.80 with the support
share, i.e. it rewarded unsupported chains); W potential fails (82% local); literature density (PubMed records on the
intervention and the outcome) fails its own question: 63% zero because trials name their programmes in their own words, so
it measures wording, not novelty. These may pass on pools of frontier hypotheses with written mechanisms; they are re-checked
there before use.

## 9. Flags (inputs for improving the hypothesis)

| Flag | Meaning |
|---|---|
| build_mechanism | no engagement, pathway or effect link: the mechanism is not written |
| name_supported_alternatives | no proposed alternative has support |
| improve_experiment | supported alternatives are left standing by the stated experiment (headroom above V) |
| find_primary_report | a review restates a trial whose own paper was not found |
| contested_link | a link has records for and against of comparable weight |
| <id>_established_by_approval | a link was taken as at least 5/6 by the approved-action rule |
| retracted_source_dropped | a retracted paper was found and given no weight |

## 10. Reports

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
list), *Evolution* (every pair: mode, P, support share, novelty with the drift flag, I, scope, the change of the score under
each profile; a placeholder when the pool has no evolution results; no shortcut button elsewhere), *PubMed papers* (every
paper with its quote and the hypotheses that use it), *Help* (how to read the report, the record weight table of v3.6 with
its GRADE domains, S as a log-likelihood sum, the evidence balance, R and P, the reading rules, novelty, the experiment and
the other indicators, the profiles from the configuration, room and evolution, limits and validation status including the
outside checks (section 12), provenance, and a glossary of every parameter).

*Style* (fixed in the template; change it there): dark green header band (#1E4D40) with the method version badge; serif
titles (Noto Serif), Inter for text; every column header, chip and number has a hover note that floats above the table; one
item per line where a cell holds several (no wrapped "a / b / c"); long headers wrap to two lines instead of widening the
column; the page uses the full window width (up to 1920 px) and a larger base size on desktop (17 px from 1280 px, 18.5 px
from 1680 px, 20 px from 2200 px). Colours carry meaning only for direction (red against, green for, amber for flags).

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

Reports on private hypotheses stay in the private repository (`longevity-kg`).

**A report written by a model from this manual** (section 0) follows the same order for one hypothesis: summary (P, support
share, novelty with the record that sets it, I, scope, places under the three profiles if there is a pool, and the room to improve under each), the chain table
(id, type, claim, S with interval, R, F / A, link novelty level, main records), why (what lifts, what lowers, the
alternatives), what to improve (actions with the score they would give, and the change of novelty they would cost),
limitations, provenance. The older one-hypothesis report by code (`python -m hyparena.analyze`) still uses the v3 / v3.1
levels.

## 11. Improvements and evolution

**The improvement list** (`hyparena/card/improvements.py`) is computed by code from the analysis of each hypothesis and
shown in its report ("What would raise it"). Each item says what to do, which link or alternative it concerns, the facts it
rests on (PMID and quote) and its expected effect: the indicators before and after and the score under each profile before
and after, computed by the same rules with the item done (fixed scales, so the expected score does not depend on the pool).
Items fall into two classes:

| Class | Item | When it appears | Expected effect computed as |
|---|---|---|---|
| fixable by rewriting | experiment_alternatives | supported alternatives the stated experiment leaves standing | I with those alternatives ruled out |
| | rewrite_refuted_link | a link the data are against (S < 0.5) | P without the records against (an upper bound) |
| | narrow_population | records for come from an adjacent population, age or sex | P and support share with those records in the exact context |
| | write_mechanism | the chain is the outcome only | not computable in advance (depends on what is found) |
| | clinical_endpoint | the endpoint is a biomarker or a self-report | the score with the endpoint "function" |
| needs new data | support_link | a link with weak support (0.5 ≤ S < 5/6) | P and support share with the link at 5/6 |
| | check_link | a link without any record | the same |

**Room to improve** (`improvements.room`, user decision 2026-11-07; replaces the "room to grow" profile). All computable
"fixable by rewriting" items of a hypothesis applied together (the experiment rules out the supported alternatives; the
refuted links are rewritten; the populations are narrowed to where the data for are; the endpoint is moved to function), then
scored under every profile on the fixed scales: the room is the expected score after minus now, per profile. It is shown in
each profile's ranking table and above the improvement list of each hypothesis, with the change of novelty it would cost
(narrowing a population moves towards the known). "Write the mechanism" cannot be computed in advance and is marked, not
counted. Two items are upper bounds, so the room is too: a rewritten refuted link is scored without its records against,
and an experiment is scored as if it already ruled out the alternatives.

**Choosing hypotheses for evolution** = the largest room under the profile the user names
(`python -m hyparena.card.evolve_v3 --top 10 --profile frontier --dry` prints the choice free; without `--dry` and with
`ALLOW_PAID=1` it runs the evolution). On the prospective pool (55 ranked trials): a positive room for 50 (evidence), 51
(funding) and 45 (frontier); median +0.10, +0.04 and +0.06, largest +0.30, +0.22 and +0.64 (frontier: a refuted link
rewritten lifts P from low to 1, and P is its second tier). The commonest item is the experiment that rules out the
alternatives (42 hypotheses), then the endpoint (23) and a refuted link (14). The top 10 by room share 9 hypotheses between
evidence and frontier: on registry trials the room comes mostly from the same fixes, whatever the profile. Novelty would
change for one.

**Evolution** (`hyparena/card/evolve_v3.py`, on request) improves chosen hypotheses and scores the improved versions
the same way as every hypothesis. **Tuning and free evolution are separate, named modes** (user decision 2026-11-07): a
tuned version is the same hypothesis with its fixable defects repaired; a free version may be another hypothesis.

| Mode | Purpose | What the writer may change | Novelty | How the improved version is scored | Report label | Status |
|---|---|---|---|---|---|---|
| tune (доработка), `--mode tune` | repair the "fixable by rewriting" items | only what the items say, from their facts; the parent's new parts (links at "analog" or "new link") must stay | **constraint**: a version that moved towards the known (`novelty_v34.drift`) goes back to the writer with the reason, once (`retries`); if it still drifts it is kept with the flag and "constraint not kept" | the whole pipeline again on the new text, parent's cut-off | "tuned version" | implemented (prompt `evolve_v3/v2`), not yet run; the first run (below) was this mode before the constraint, with prompt v1 |
| free (свободная эволюция), `--mode free --profile P --writer F` | get the best hypothesis for the profile P | everything (claim, mechanism, population, outcome, experiment); the writer is told the profile's order and whether novelty comes first; it names the papers it relies on | **flag only**: a move towards the known is shown, not forbidden | the whole pipeline again; the papers it named count only if the verifier finds them with a verbatim quote before the cut-off (named / found are reported); distance from the parent = 1 − Jaccard of content words; above 0.7 the version is marked "new hypothesis after" the parent | "free evolution" (+ "new hypothesis after") | implemented (prompt `evolve_free/v1`), not yet run; for current pools only (the writer knows literature past the cut-off); the user's preferred mode for improving |
| controlled | test whether the list predicts the gain | one item at a time | — | the parent's card, records and alternatives are kept; only what the item changes is re-checked | — | planned |

Both modes report, next to the drift flag, the **share of links with support before the cut-off**, parent → child: a version can
keep its novelty level and still be assembled from known pieces; a rise above 0.25 is pointed out in the report.
Choosing whom to improve: `--top K --profile P` (the largest room to improve, below). Tuning: one call writes the text, about
21 calls per improved hypothesis, up to twice that with a retry; free evolution: about the same, with the writer named by
`--writer`.

**First run** (2026-11-06, `specs/evolution-v3-pilot-2026-11-06.yaml`): the top 10 of the pilot under the evidence
profile; about 311 calls (about 0.8 USD). The score under the evidence profile rose for 2 and fell for 8 (down to −0.17),
against an expected +0.04 … +0.11. The reason is the design of the mode, not the hypotheses: (1) the whole pipeline ran
again, so a new card, a new search and new alternatives changed everything at once (I fell for 3, because the alternatives
were proposed anew, not the same ones); (2) the prompt's layout asked for a mechanism line every time, so every version
wrote out a mechanism, the chains grew by 2 to 7 links, the new links were checked and often found weak or contested, and P
fell in 9 of 10 (e.g. 0.93 → 0.26). The useful side: writing the mechanism out shows the links a hypothesis rated well on its
outcome alone actually rests on. The controlled and free modes above answer the two flaws.

**Novelty control** (v3.4, `novelty_v34.drift`, user decision 2026-11-07): a writer model tends to pull a hypothesis towards
what is already known, because that is where the data are. Each pair is flagged **"moved towards the known"** when the
child's novelty N is lower than the parent's (both known), or a link kept in the child (same text) has a lower link level
(for example "only in mice" → "a human trial exists"), or the parent's new link is gone and the child has no new link. The
child is never excluded: it stays in the ranking, and its lower novelty lowers its score where N is an indicator (funding,
frontier). The flag is checked by hand-made drifted pairs (a human trial added on the outcome, a related compound
in place of the intervention's records, the new link removed, a kept link moved down) which must all be flagged, and
controls (an identical child, support added at the same level, a new link added) which must not (`tests/test_v34.py`). In the
first run 1 of 10 pairs was flagged (analog → new context). The improvement item "narrow the population" shows its expected
change of novelty next to its gain, so the cost of narrowing towards the known is visible before it is applied.

**The report section "Evolution"**: a table parent → improved version (P, I, support share, novelty with the flag, and the
score under each profile, rises in green, falls in red); per pair, collapsed: the items applied, what changed in the text and on which fact,
the expected change of each item against the change obtained, the mechanism links added or removed, the improved text; at
the end, the mean change of the score by kind of item. Hypotheses without an improved version are listed with the reason.
The improved versions also appear in the ranking (section 10).

**Limits.** Evolution in the implemented and controlled modes makes no new evidence: P can rise only by moving the text away
from what the data are against, the support share only by fitting the text to what was already found (which is exactly the
drift towards the known that the novelty flag shows), and a rise of I is a design that is still to be carried out. The improved text is written from the
findings of the verifier that then scores it (circular), so a rise of the score says what to change, not that the
hypothesis became better. In the free mode new evidence counts only when the verifier finds it; the writer's own knowledge
reaches past the cut-off date, so the free mode is for current pools (scored as of today), not for retrospective samples.
A gap between the expected and the obtained change points at the improvement list (its estimate was wrong) or at the
rewrite (the item was not applied as asked); both are shown. "Needs new data" items are never applied by the first two
modes.

## 12. What the method does not do, its known limits and its validation status

- It does not predict whether a trial will succeed; trials are run where support exists but the question is open.
- The verifier keeps about 60% of relevant papers with almost no false ones (measured on three hand-labelled sets): support
  from interventions of the same kind is often missed, so P is biased down for programmes and behavioural interventions.
- Abstracts by default; full texts only where a knowledge-graph row says so.
- Alternatives come from a model, not yet from the knowledge graph.
- P (v3.4, now named non-refutation) is 1 for about two thirds of registry hypotheses: it says "nothing refutes it" and
  nothing more (whether to keep it as a separate indicator is open, user 2026-11-07); the order among
  them comes from the support share, I and the other indicators of the profile.
- Novelty depends on the verifier's recall: a paper it missed makes a hypothesis look newer than it is (about 40% of
  relevant papers are missed). Novelty is therefore an upper estimate; the "known result" gate catches only exact matches.
- Novelty is read off the outcome link first: a known effect with a new mechanism counts as new context, not as new.

**Outside checks by a second reader (Argon, blind; 2026-11-08; specs/record-weight-2026-11-08.yaml,
informativeness-check, novelty-check, balance-check):**

| What | Agreement | Reading |
|---|---|---|
| order of pairs of records (R4) | τ-b 0.10 with v3.6 weights, 0.04 with v3.5 | v3.6 adopted; a meta-analysis now weighs at least as a single RCT |
| design, n, blinding of a record | 92-96% | reliable fields |
| context label ("same class") | κ 0.10-0.22 | the weakest field of the verifier: class is not charged in v3.6 |
| d of the alternatives | κ 0.005-0.07 before, 0.35 after judging from the registry text | adopted 2026-11-08; I and the room recomputed |
| support a of the alternatives | Spearman 0.28 | the reader is generous (knowledge), ours counts found papers |
| novelty N | weighted κ 0.14 (0.26 with verifier v11); the reader is nearer the known in 21 of 37 trials, farther in none | N is overstated: read the frontier profile with that caveat |
| missing competitors | in 78% of trials the reader adds a supported one; a checklist prompt covers 15 of 40 fully, 13 partly | not yet in the method |
| evidence balance per link | pack 8, pending | |

**Reader noise.** Reading the same papers again moves the evidence balance of the 59 prospective trials (Spearman 0.76
between two readings); close places in a ranking are within that noise (specs/record-weight-2026-11-08.yaml, reader_noise_v9).

**Deferred from the outside review (2026-11-07), each paid or an inflation risk:**
- I depends on alternatives already published, so a new field gets I = 0 even for a well-built experiment. Planned: a
  second half of I for the rigour of the design (controls, blinding, factorial or dose and timing inversion), scored by two
  model families with only agreement counted, since a well-described experiment is cheap to write.
- Opposite effects in different regimes (timing, dose, polarity) are read as a conflict ("contested"). Planned: the regime
  of the intervention in the verifier's extraction, F and A summed only within comparable regimes.
- Every unchecked link starts at S 0.5. Planned only as a prior from databases by code (target evidence in OpenTargets or
  ChEMBL), in narrow bounds about 0.4–0.6 and after the admission check; never a model's judgement.
- Precision from full texts (PMC open access, numbers only) instead of the constant before the outcome.
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

## 13. Worked example (computed by the code)

Hypothesis: "x activates AMPK, AMPK suppresses senescent cells (hallmark: cellular senescence), and x improves function in
older adults". Records: two mouse studies for c1 (n = 40 each, large effect, between groups); none for c2; one RCT of 120 for
c3 (medium effect). One proposed alternative with an observational study of 300 for it, cut off by the stated experiment.

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

Under v3.6 the RCT of 120 with a medium effect weighs 0.839 (its effect counts in full), each link's S comes from F − A,
and a mouse null of 40 weighs by its power (0.24; preclinical design 1, between groups 1) against 0.5 for the
mouse study for, so it lowers the balance less than under v3.5 (0.455 vs 0.333).

Under v3.4 the c1 records weigh more (precision 1/2 before the outcome), P is 1 until something is against, the study for c2
raises only the support share, and the study against c2 cuts P to 0.23. Novelty: new context (an RCT on the outcome exists).
Under v3.3: the study for c2 lowers P slightly and raises the support share; under every profile the expected score rises (evidence
0.667 → 0.703 on these two alone). A study against c2 cuts P to 0.12: data against are what P is for. Under v3.2 the first row had
P 0.380 (c2 at 0.5), the penalty for writing out the mechanism that v3.3 removes.

## 14. Constants (checked against the code)

```yaml
v32:
  c_anchor: 6.666667          # 4 / 0.6
  fold_rest: 0.25
  precision: {floor: 0.25, full_at_n: 300}
  effect_d_full: 0.8
  p_floor_aspid: 0.01
v36:
  loglr_lambda: 2.682397     # 2 atanh(2/3) / 0.6
  design_grade3: {rct: 1.0, meta_analysis: 1.0, non_randomised: 0.5, observational: 0.5, other: 0.25}
  effect_full_from: 0.71875  # the continuous effect weight of d = 0.5
v34:
  preclinical_precision: 0.5
  novelty_levels: [new_context, translation, analog, new_combination, new_link]
link_thresholds: {moderate: 0.6, strong: 1.5, strong_min_independent: 2}
informativeness_cap: 1.5
effect_unclear_weight: 0.5
precision_bands: [30, 100, 300]
scales:
  design_human: [cells, animal, observational, review, non_randomised, meta_analysis, rct]
  design_animal: [cells, review, animal]
  precision: [lt30, "30_99", "100_299", ge300]
  effect: [none, small, medium, large]
  comparison: [none, within_group, between_groups]
  context: [class, adjacent, exact]
  link: [refuted, contested, unverified, weak, moderate, strong]
  link_v31: [refuted, unverified, contested, weak, moderate, strong]
  alt_support_v31: [weak, moderate, strong]
  scope: [local, organ, hallmark]
  discrimination: [unchanged, weakened, eliminated]
effect_class_rule_a:
  ratio: {medium: 1.25, large: 2}
  standardised_difference: {medium: 0.5, large: 0.8}
  percent: {medium: 5, large: 20}
profiles:
  evidence: [[chain_state], [I], [W], [best_design_outcome, independent_outcome, endpoint_clinical]]
  funding: [[chain_state], [feasibility], [trend_pubmed, ai_role, N], [I], [W, endpoint_clinical, best_design_outcome, independent_outcome]]
  frontier: [[N], [chain_state], [I, feasibility]]
```

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

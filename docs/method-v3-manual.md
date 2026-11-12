# Method v3 manual: how a hypothesis is scored and how to read the report

Version: rules **v3.9** (2026-11-11) = v3.8 with the novelty level "new mechanism of a known effect" (section 7: the effect
on the outcome was studied, but a link between supported neighbours is new by a PubMed count) and the card as the union of
two parses (section 3), the weight of a meta-analysis by its GRADE certainty and the design from PubMed's publication types
(sections 4, 5; specs/meta-and-nulls-2026-11-09.yaml: R2 0.697 and R3 0.582 against 0.702 and 0.593, inside the 0.03 rule). v3.8 (2026-11-11): a third
level of the intervention match, "same category only", counted as adjacent (reading rule 1, section 4). v3.7 (2026-11-09): the record weight of v3.6 on the GRADE domains (section 5), link strength as a sum
of log likelihood ratios (section 6), the evidence balance over the links that have data (section 7), the ASPID profiles
(section 8) and the rules every improved version keeps (section 11). Code: `hyparena/card/rules_v32.py`
(`evaluate(..., v36=True)`, `EMPTY_SLOTS = "skip"`), `hyparena/card/novelty_v34.py`, `hyparena/card/aspid_v3.py`,
`configs/profiles_v3.yaml`. Every rule has its check in `specs/` (named in the section); how the earlier versions
differed (v3.0-v3.6) is in [`archive/method-history.md`](archive/method-history.md). The constants (section 14) and the worked
example (section 13) are checked against the code by `tests/test_manual.py`: if the code changes, the test fails until this
manual is updated.

## 0. Using this manual as context

Attach this manual to a hypothesis (and, if available, the literature found for it) and ask for a report in the template of
section 10. Rules for a model writing such a report:

- Score only what the literature you were given says; every record needs a PMID and a verbatim quote. A record you cannot
  quote does not exist.
- Use the scales and formulas of sections 5-7 exactly; show the arithmetic for each link's S, the evidence balance and I, and the
  record that sets the novelty level.
- Do not predict the outcome of the trial; the evidence balance is the state of the literature before T, not a forecast.
- **The hypothesis is the object, the experiment is its test** (2026-11-12): score the experiment as it is stated and never
  invent one, nor links the text does not state; proposals for a better experiment belong only to the improvement list and to
  versions, which are labelled as such.
- When you evolve or improve a hypothesis, keep the rules of section 11 ("Rules every improved version keeps"): no record copied, edited, moved or dropped by hand, supported links kept, novelty-by-absence counted on the link's own subject and object.
- When in doubt between two levels, take the lower one and say why. For novelty, take the level nearer the known: a paper you
  were not given may exist, and missing data are never novelty.
- Use the names and the help section of section 10a: no code shown alone, no new names for existing terms.
- **What the experiment does to an alternative (d) comes only from the registry text as it stood at T** (section 7): never
  from the trial's own publications or anything published after T, and never from a design label alone ("randomised",
  "placebo-controlled", "factorial"): name the arm and the result that would rule the alternative out, or give at most
  "weakened".
- **Numbers only code computes** are written "не вычислено" unless you ran the count yourself and show the query, the date
  and the number: rising attention in the literature, every PubMed count (novelty by absence, rule 6 of section 11, and the
  level "new mechanism of a known effect"), literature density. Feasibility is computed by the formula of section 8, not
  estimated.
- **A version is scored on its own links**: every indicator of a version (balance, coverage, support share, I, scope,
  novelty) is recomputed from the version's chain; nothing is copied from the parent.
- **Use the short ids you are given** (section 10, the hypothesis database); do not number hypotheses yourself.
- A report written this way is an approximation. The authoritative report is the one the code builds
  (`python -m hyparena.analyze RUN.json`), from the same rules and the records the verifier extracted.

## 1. What is evaluated

A hypothesis is valued for its **mechanism**: a chain of links from the intervention to the outcome. A hypothesis is
promising when the key links are not refuted by current data and the mechanism, if true, would change the question a lot.

The method computes **axes** (what can be checked against the literature) and then ranks hypotheses by **ASPID** under
several **profiles** (whose order of importance says what matters to whoever ranks):

| Axis | Question | Range |
|---|---|---|
| evidence balance | How strongly does the literature before T support the chain's links (for minus against), over the links that have data? | −1 … +1 |
| coverage | How many links of the chain have any data at all? | k of n links |
| N, novelty | How far is the hypothesis from what was already asked before T? | new context < translation < analog < new mechanism of a known effect < new combination < new link |
| I, informativeness | Which supported competing explanations does the stated experiment cut off? | 0-1 |
| W, scope | How far does the supported mechanism reach: one condition, an organ or system, a hallmark of ageing? | local, organ, hallmark |
| feasibility | Can the stated experiment be run: system, duration, planned n, readiness of the intervention? | 0-1 |

**ASPID** (section 8) is the aggregation: each profile orders the indicators by importance, weights are drawn at random
under that order, and a hypothesis gets an expected value and the probability of being in the top. A chain refuted by
strong data is filtered by the gate (section 6) and not ranked.

Only the evidence balance is meant to track trial outcomes; I, W and feasibility describe what a result would teach and what
it costs, whatever the result; N says how far the question is from what was already asked. Validation status is in section 12.

## 2. Inputs

- The hypothesis text as written (a registry entry, a grant proposal, a pitch).
- The date T: only papers public on or before T count (the evaluation is "as of T").
- For registry hypotheses, the registry fields (population, design, control, planned n, primary outcome). For
  ClinicalTrials.gov the text given to the card now carries them (user decision 2026-11-11, `scripts/benchmark_run._ctgov_design`):
  allocation, model, masking and purpose; the arms with their type and description; the planned enrollment only while the
  registry gives it as planned (an actual count is written after recruitment). Texts built before 2026-11-11 lacked them (the
  prospective pool: design, control and n "unknown", so the judge of d had no arm to name); frozen scores are not changed.

## 3. The card

A model (the normaliser) turns the text into a card:

- **Claims** with roles, and for the mechanism a **link** type: `delivery` (the intervention is given and reaches the tissue),
  `engagement` (it acts on its target), `pathway` (the target changes a pathway), `effect` (an intermediate effect),
  `outcome` (the clinical or functional outcome). If the text argues a mechanism, the chain must be written; a missing link
  is a flag ("build mechanism"), not an error. The link types are our adaptation of accepted schemes, not a standard
  ontology: delivery, engagement and pathway / effect follow Pfizer's "three pillars" of Phase II survival (exposure at
  the site of action, target binding, functional pharmacological activity; Morgan et al., Drug Discov Today 2012;17:419-24),
  and the chain of steps with a strength per step is built like an adverse outcome pathway (molecular initiating event,
  key events, adverse outcome, weight of evidence per key-event relationship; Ankley et al., Environ Toxicol Chem
  2010;29:730-41; OECD AOP Users' Handbook). For an intervention that is not a compound, delivery means it was carried out
  (adherence). Whether this decomposition is better than others is tested in `specs/mechanism-chain-comparison-2026-11-11.yaml`.
- **Hallmarks of ageing** on engagement, pathway and effect links when the link concerns one.
- **Population** (for registries taken from the registry fields).
- **The stated experiment**: design, control, planned n, primary outcome.
- **Alternatives**: competing explanations, proposed by a second model call from the literature found, each with its support.
  They are proposed after the first search and reading (up to 25 abstracts found for the hypothesis; prompt
  `propose_alternatives`: up to 5, after going through seven kinds of competitor — expectation and placebo; attention and
  supervision; co-interventions; selection and attrition; measurement and learning; regression to the mean and natural
  course; another biological route), then searched and read like claims (their support comes from the records found, the
  model's PMIDs only seed the search; since 2026-11-11 a finding counts for an alternative only when it shows the part that
  differs from the hypothesis — for "attention and supervision" an effect of attention itself, not that the exercise works:
  on H49 that alternative had been "supported" by meta-analyses of resistance training), and what the experiment does to
  each is judged from the registry text (section 7).
  **Asymmetry, on purpose** (user decision 2026-11-11): the mechanism is taken strictly from the text (the hypothesis is
  scored as written), while competitors are looked for more widely than the author named them; their weight still comes
  only from literature found before T.
- **Method v2 layers off under v3** (2026-11-11, config `legacy_v2_checks`, default off for `method: v3`): the mouse probes
  ("the same intervention extends lifespan / improves healthspan in mice", added to every human hypothesis) and the
  checklist alternatives with their checks. v3 scores neither; on H49 they cost 4 + 2 calls (about 36 thousand tokens) and
  gave nothing.
- **AI role** (normaliser v10): none / AI analyses the data / AI in the experiment loop / AI is the intervention, with a
  verbatim phrase of the text; without one the code sets "none". An indicator of the investor profile only.

**Two parses, one card** (v3.9, user decision 2026-11-11; `normalizer.normalize_union`, config `normalize_runs: 2`). Two
parses of the same text at temperature 0 differ: on H49 the first wrote no mechanism, the second wrote two intermediate
effects, both with verbatim spans. The card is the union of two independent parses: a claim of either parse counts if its
span is verbatim; claims are matched by subject, relation and object (and the measure, where the object is the organism);
the first parse keeps its ids and its single outcome claim (an outcome claim of the second becomes a premise); edges are
carried over; a field of the experiment or the population unknown in the first parse is taken from the second; a conflict
keeps the first and is recorded. The agreement of the parses (shared claims / all claims) is kept as the card's stability.
Cards made before 2026-11-11 come from one parse.

**A direction for value links** (normaliser v11, user decision 2026-11-11). "Changes a value" (`changes_biomarker`) is
kept only when the text gives no direction anywhere; otherwise the link says which way ("promotes", "suppresses", or
"improves healthspan" with the measure), with the span from the sentence that states it. On H49 the undirected link
"squats change body composition" got 11 findings from the reader, all "neither": with no direction there is no side to take,
and a null on muscle mass could not count against.

**Spans for the core fields** (normaliser v12, user decision 2026-11-12; `rules.core_span_problems`, `rules.anchor_core`).
Until v11 only the claims (and the AI role) carried a verbatim span; the population, the interventions, the comparator, the
outcome and the stated experiment were filled by the model from the text with nothing checked against it. From v12 each of
them carries `span`, the shortest exact phrase of the text that states it, checked by code like a claim's span and sent back
to the model with the problem for up to three rounds. A field whose value is known but has no verbatim span after the rounds
keeps its value and is listed in `unanchored`: the report shows it as "from the text, not anchored" (two labels in
`docs/system/card.md`). Cards made before v12 have no spans and are not checked for them. The working config stays on v11
until the card benchmark (`specs/benchmark-card-2026-11-12.yaml`) compares v11 and v12.

**Normaliser v13** (user decisions of the card walkthrough, 2026-11-12; `normalizer.derive_roles`, `v13_code_fields`; the
core and the reference fields are listed in `docs/system/card.md`). On top of v12:
- **background**: what every group receives alike (the same exercise programme in both arms, standard care for all) is
  `pico.background`, not an intervention; only something done to the participants (not a measurement or a condition held
  equal); it carries a span like the other core fields;
- **primary and stated_as in place of role**: a claim states its place in the chain (`link`), whether it is the main outcome
  (`primary`, one claim with link outcome) and how the text states it (`stated_as`: claimed, known, analogy). `role`, read by
  the earlier rules, is derived by code: the primary outcome is `outcome`, an analogy `analog`, a claimed step before the
  outcome `mechanism`, the rest `premise`. Requires edges are no longer asked (the order is the link's);
- **level** of each claim (molecule, cell, tissue, organ, organism): reference only, not scored until it agrees with the
  outside reader (card benchmark);
- **expected effect** (size, what it is compared to, time point, span) when the text names one; the outcome's direction;
- **one comparator vocabulary** (placebo, sham, active, usual care, no intervention, unknown); the experiment's `control` is
  set from it by code; the experiment's **duration class by code** from the stated duration (under 90 days weeks, under 2
  years months, under 10 years years, else decades; before v13 the model chose it and was not consistent); the primary
  outcomes as a list (several are equal, section 7);
- **registry design fields by code** (allocation, model, masking and who is masked, purpose, arms with their types, planned
  enrollment) from the lines the text builder writes, kept as `decisive_experiment.registry` (reference; an input of the
  planned code rule for d); **references the text names** (PMID, DOI) as `author_refs`.
**v14** (2026-11-12, after the card benchmark): every step on the way to the outcome keeps its link whether claimed or known (v11-v13 also told the model that a background premise has no link, and v13 put 37 known steps off the chain); pathway is a molecular or cellular process, effect a state of a tissue or organ. Edges between claims are no longer asked (no rule reads them: the chain order is the links'; the field stays for old cards; a use is foreseen in the knowledge graph). Saved cards (v10, v11) keep their fields and scores; nothing is recomputed. The working config moves to v13 only after the card
benchmark (`specs/benchmark-card-2026-11-12.yaml`).

**What the normaliser is given** (`hyparena/prompts/normalize_card/v11.j2`): the text only (for a registry trial the
registry fields as "Name: value" lines, section 2), the closed lists of relations and hallmarks, the rules for every field,
two worked examples of other hypotheses and an empty JSON skeleton. Not the date T, not the literature, not other
hypotheses. The code then checks the schema and the verbatim spans (up to three rounds; a claim without a verbatim span is
dropped), retries once with a hint when the outcome relation is "other", and fills the endpoint and the population of a
registry text from its fields.

## 4. Evidence records

A verifier model reads each abstract found for a claim (PubMed, date-cut, queries written by a model, citation expansion) and
returns records:

- a verbatim quote (checked by code; a quote not in the abstract is dropped);
- stance: supports / refutes / neither (only supports and refutes are scored);
- from the whole abstract: `design` (rct, non_randomised, observational, animal, cells, review, meta_analysis, other;
  since 2026-11-11 PubMed's own publication types decide where they are decisive: "Meta-Analysis" is a meta-analysis,
  "Systematic Review" and "Review" are reviews with their kind kept (systematic / narrative), a "Randomized Controlled
  Trial" the reader called a review is an RCT; `review_kind.design_from_pubtypes`; a meta-analysis also gets its GRADE
  certainty from the abstract by code, `certainty_from_abstract`),
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
   programme; another drug of the same class) — it counts at full weight under v3.6 (the class label is not charged while it is
   unreliable). *category* (v3.8, adopted by the user 2026-11-11, `specs/intervention-class-2026-11-11.yaml`): only the same broad
   category (another single nutrient for a multi-component formula, another diet for "nutritional supplements", another
   exercise modality for a specific programme) — it counts as adjacent, 1/2 (`rules_v3.context_level`). The paper-skeleton
   pair model reads the four levels; the verifier of the saved runs never wrote "category", so their scores do not change;
   against an outside reader (Argon, 80 pairs blind) the four levels agree at weighted kappa 0.55. The match is judged at the level at which the
   claim names the intervention (verifier prompt v10, 2026-11-08): when the claim names a kind ("resistance training",
   "adequate protein intake", "a home-based exercise programme"), any study of that kind is exact; class only when the claim
   names a specific product, compound or programme and the study used another member of its kind. A programme that merely includes the named
   intervention among several components (resistance training + nutrition + cognitive training for "squats") is *class*, and
   only when its result can be read for the exercise arm; otherwise it is not a record for this claim. *Another intervention
   altogether* (aerobic training for a resistance claim) weighs 0.
2. **Against means null or opposite, not small.** A record is *against* when the result for the claim's own measure is no
   effect (not significant against control, or no change in a before-after design) or the opposite direction. A significant
   effect judged clinically small (below a minimal important difference) is a record *for* with a small effect (effect weight 1/2),
   not a record against. A null on another measure of the same study is not against this claim (it may be against another
   link of the chain).
3. **Comparison is read from the analysis behind the sentence, not from the number of arms.** "X did not change in either
   group over 12 weeks" is a within-group (before-after) result, 1/2, even in a two-arm trial; "no difference between groups"
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
| design (starting level), outcome link of a claim about humans | RCT 1; meta-analysis by its GRADE certainty (2026-11-11): high or moderate 1, low 1/2, very low 1/4, not reported 3/4; non-randomised and observational 1/2; review (systematic or narrative), animal, cells, other 1/4 |
| design, links before the outcome or a claim about animals | cells 1/3, review 2/3, primary study 1 (unchanged) |
| precision (imprecision) | record for: min(1, ln n / ln 300), at least 1/4, n unknown 1/4; before the outcome 1/2. Record against (a null): the power of its study to detect d = 0.4 (v3.5) |
| effect (rating up for a large effect) | record for: a stated effect of at least medium size (d ≥ 0.5, ratio ≥ 1.25, ≥ 5%, the authors' "moderate") 1; small, none or not stated 1/2. Record against: 1 |
| comparison (part of risk of bias) | between groups 1; within group or none 1/2 |
| context (indirectness) | adjacent 1/2 (another population, age, sex, dose, comparator or species, only on qualifiers the claim states; or an intervention of the same broad category only, reading rule 1); exact and class 1 |

A record against (a null or opposite result from a comparison) is weighed by the power of its study to detect d = 0.4 in
place of precision and effect (two-sided 5%; between groups Φ(0.4·√(n/4) − 1.96), before-after Φ(0.4·√n − 1.96), n unknown
→ 40): a null of 20 people weighs little, a null of 300 fully. A record about another intervention altogether weighs 0.
Retracted papers weigh 0.

**Folding by independence group.** On each side (for, against) the records of one group (one trial, or one paper) are
folded: the heaviest counts fully, every further record of the group 1/4. F and A are the folded sums. The fold runs per
link, so one paper can count on several links of a chain (a candidate rule for the same finding on several links:
`specs/v38-candidates-2026-11-10.yaml`, C2).

**The distance to the clinic is charged once.** Links before the outcome use the preclinical design scale (cells 1/3,
review 2/3, primary study 1) with precision 1/2 (replicates of cells or animals are not comparable with trial
participants), and the context factor charges another species there; on the outcome link of a human claim another species
is charged by the design scale only.

The weight tables of v3.2-v3.5 are in `archive/method-history.md`.

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

Reference points (v3.6; the worked example of section 13): one RCT of 120 with a medium effect, between groups, in the
exact population weighs 0.839 on the outcome link (S 0.905 alone); one mouse study of 40 with a large effect, between
groups, on a link before the outcome weighs 0.5 (S 0.793); a mouse null of 40 weighs 0.24 by its power. A link without
records has S 0.5 and is left out of the evidence balance (section 7). The Beta strength of v3.2-v3.5 and the discrete
labels of v3 / v3.1 are in `archive/method-history.md`.

**Approved action.** An engagement link whose subject is one approved drug (ChEMBL phase 4) with one of its ChEMBL targets
named in the link is taken as at least 5/6 without search.

**Gate (the only filter).** A key link is refuted when there is a record against of the top design (RCT or meta-analysis),
between groups, in the hypothesis's population, and no record for of that level. Then the hypothesis is filtered (not
ranked). Nothing else filters: an undeveloped but promising hypothesis keeps its score and gets flags.

## 7. Axes

- **Evidence balance** (v3.7; `chain_state`), the main axis of every profile = the mean of 2S − 1 over the chain's **slots that
  have at least one counting record**, from −1 (the data are against the links) through 0 (for and against balanced) to +1
  (supported). A slot is one link; consecutive pathway links are one slot (its best link); parallel outcomes are one slot
  (the primary, else their mean). Since 2026-11-11 (H49 walkthrough): the mean is over the parallel outcomes that have a
  counting record (an empty outcome is not averaged in, as an empty slot is not since v3.7: on H49 it pulled a supported
  slot from 1.0 to 0.83 and would have softened a refuted one); the primary is the outcome matching the registry's primary
  outcome by its words; when the registry lists several primary outcomes there is no single primary (they are equal; H49
  lists SPPB and body composition); with one primary outcome and no word match, the card's own outcome claim is primary. A slot with no record is not averaged in (v3.7, user decision 2026-11-09): under v3.6 it
  entered as 0, so an added untested link lowered a positive balance by k/(k+1), raised a negative one towards 0, and cost
  nothing when written as a pathway next to another pathway; the result depended on the sign and on the link type chosen.
  Gaps are shown by the coverage (share of slots with data) and the improvement item "check the link", not by the balance.
  Check (specs/empty-slots-2026-11-09.yaml): R3 0.593 → 0.586, agreement with the outside reader's trial balance 0.393 →
  0.398, 12 of 59 prospective units move, rankings Spearman ≥ 0.99. A consequence to read correctly: the balance is the
  state of what is known, so a first modest record on a link that had none can lower it (worked example, section 13).
- **Coverage**: the share of the chain's slots with at least one counting record. It says how much is known; the balance
  says how strong it is. The report shows the chain with its empty links; a coverage column next to the balance is a
  pending candidate (`specs/v38-candidates-2026-11-10.yaml`, C4).
- **P (non-refutation)** and the **support share** are still computed by the code (P for the history and the support share
  for older reports) but are in no profile; definitions in `archive/method-history.md`.
- **W, scope**, from supported links only: a hallmark of ageing (needs a link at least moderate), an organ or system, else
  local. A scope that is claimed but not supported counts as local. An indicator of ASPID. A hallmark is
  the link's own object (a measured hallmark process: senescent cells, proteostasis markers, mitochondrial function), not
  something inferred from the kind of intervention: "protein after exercise → muscle protein synthesis" is an organ link,
  not the hallmark "loss of proteostasis".
- **I** = min(1, Σ a·d / 1.5) over the proposed alternatives, from 0 to 1. **Headroom I** = the same with d = 1 for every supported alternative. a = support of the alternative, max(0, 2 (S − 0.5))
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
  copied verbatim (an "eliminated" without one becomes "weakened"); the registry text is the one current at T (for a
  retrospective trial, the version registered before T), never the trial's publications or other texts after T (an outside
  report took the separating phrase from a trial's results paper, 2026-11-11); on a holdout of 30 trials it agrees with the outside
  reader at κ 0.35 (specs/informativeness-check-2026-11-08.yaml). The support a is unchanged: from the records found.
- **Headroom I** = I if the experiment cut off every supported alternative (d = 1): what improving the experiment could
  add; an input of the room to improve (section 11).

- **N, novelty** (v3.4, `novelty_v34.novelty`): the distance of the hypothesis to what was already asked before T, from the
  usable records on either side (a question already asked is not new, whatever the answer). On the outcome link, by the
  closest record: **new context** (the same intervention and outcome in the claim's species, another population, age, sex or
  dose), **translation** (the same intervention, only in another species), **analog** (only a related compound or class);
  above them **new mechanism of a known effect** (v3.9, user decision 2026-11-11, `novelty_v34.new_mechanism_links`): the
  outcome has records, but a link before the outcome has none, both its neighbours in the chain are supported (S > 1/2 with a
  record for), and PubMed holds fewer than 5 records before T on the link's own subject AND object (counted by code, the
  same count as rule 6 of section 11; no count, no level). The level answers the frontier's question about mechanisms: under
  v3.4-v3.8 N was read from the outcome link only, so a new mechanism of a studied effect stayed "new context", and directed
  evolution could not raise novelty (Argon's hand run, `specs/directed-evolution-2026-11-09.yaml`). It sits below new
  combination because there the outcome itself is untested. On registry pools it is rare (mechanisms are seldom written);
  saved scores have no counts, so none moved.
  Without any outcome record: **new combination** (every link before the outcome is supported: the pieces are known, the
  chain as a whole was not tested), **new link** (at least one link before the outcome has no record and at least one is
  supported). **Unknown** when there is no data anywhere or the chain is the outcome alone: absence of evidence is not
  novelty. The exact known result (same intervention, species, sex, age and dose, supported) stays the separate
  "known result" outcome and is not ranked. The same ladder per link (`link_levels`) feeds the evolution flag (section 11).
- **Leverage** (defined, in no profile): how much the support share would rise if the bottleneck slot reached S = 5/6,
  times the mean support of the other slots, so a chain of guesses or one link alone has none. **W potential**: the scope
  with the bottleneck confirmed.

Protections against inflated hypotheses, by construction: the gate (section 6); alternatives without support weigh 0;
scope only from supported links; records of one trial or paper count once; novelty is unknown, not high, without data.

## 8. ASPID: indicators and profiles

Values sit on fixed scales, so a hypothesis's expected value does not depend on the rest of the pool. An unknown value is
drawn over its whole range in every draw.

| Indicator | What it says | Scale |
|---|---|---|
| I | informativeness of the stated experiment (headroom I, of an improved one, feeds the room to improve, section 11) | linear, 0-1 |
| W | scope | local < organ < hallmark |
| feasibility | the mean of the known parts (an unknown part is left out): system (data analysis and cells 1, yeast 0.9, worm and fly 0.85, mouse and rat 0.5, human 0), duration (weeks 1, months 2/3, years 1/3, decades 0), planned n (under 50: 1, under 200: 2/3, under 1000: 1/3, more: 0), readiness of the intervention (approved or not a compound 1, in trials 0.5, neither 0); `v3_extra.feasibility` | 0-1; does not yet count arms or invasive measures (section 11, rule 7) |
| best_design_outcome | best design among the records of the outcome link | cells … RCT |
| independent_outcome | independent sources for the outcome link | 0-5 |
| against_share | share of the chain's weight against (in no profile since v3.4: |ρ| 0.87 with P) | 0-1, lower better |
| endpoint_clinical | how close the trial's primary endpoint is to a clinical outcome (two model families agree, else unknown); with several primary outcomes the least clinical of them (prompt `estimand/v2`, user decision 2026-11-11: when in doubt, the lower level; v1 took the first named) | biomarker < patient-reported < function < clinical event |
| support_share | how much of the mechanism chain is supported: mean of max(0, 2 (S − 0.5)) over its slots (v3.3) | 0-1 |
| trend_pubmed | rising attention: PubMed records on the intervention in the last 3 years vs the 3 before, net of PubMed's growth | -0.5 … 1.5 |
| ai_role | role of AI in the hypothesis | none < analysis < in the loop < AI is the intervention |
| N | novelty (section 7) | new context < translation < analog < new mechanism of a known effect < new combination < new link |
| leverage, W_potential, literature_density | defined in code, failed the admission rule on the trial pools (below) | |

Profiles as of v3.6 (`configs/profiles_v3.yaml`). The number is the rank of importance (1 = most important; a "tier" in
the code); within a rank the
indicators are of equal rank and ASPID draws their weights under the order; "—" = not in the profile. The same table is
in the report's help (built from the config).

| Indicator | evidence (trial-5) | funding (trial-7) | frontier (trial-3) |
|---|:-:|:-:|:-:|
| evidence balance (`chain_state`) | 1 | 1 | 2 |
| novelty N | — | 3 | 1 |
| feasibility | — | 2 | 4 |
| I | 2 | 4 | 3 |
| W | 3 | 4 | 5 |
| trend_pubmed | — | 3 | — |
| ai_role | — | 3 | — |
| best_design_outcome | 4 | 5 | — |
| independent_outcome | 4 | 5 | — |
| endpoint_clinical | 4 | 5 | — |

Not in any profile: P and support_share (replaced by the balance in v3.5, still shown), against_share (|ρ| 0.87 with P),
leverage, W_potential, literature_density (failed the admission rule, below), I_headroom (an input of the room to improve).
2026-11-09 (user decision, `scripts/profile_variants.py`, calibration/profile_variants.json): funding W moved from tier 5
to tier 4 next to I (investors weigh reach); frontier I above feasibility and W added last. On the registry pools both
change little (Spearman with the previous order 0.99 and 0.98, 9 of the top 10 kept; AUC 0.611 vs 0.610 and 0.575 vs
0.584, inside the 0.03 rule), because W is local for 48 of 55 prospective hypotheses; they matter on pools with written
mechanisms, where scope varies. Funding trial-6 and frontier trial-2 were the orders before.

**Definitions of the three rejected frontier candidates** (`specs/v34-frontier-2026-11-07.yaml`): **leverage** — how much
the support share would grow if the weakest slot of the chain (the bottleneck) were checked and supported (S = 5/6), times
the mean support of the other slots: large for a chain held back by one unchecked link. **W_potential** — the scope the
mechanism would have with that bottleneck supported (local / organ / hallmark). **literature_density** — log10(1 + PubMed
records on the intervention and the outcome before T): a proxy of how much is already known (lower = newer).

There is no separate "room to grow" profile any more (removed 2026-11-07, user decision): what improving a hypothesis would
give is computed under every profile as the **room to improve** (section 11), so the profile duplicated it, and only for one
kind of improvement (a better experiment). Headroom I stays an input of that computation, not an indicator of any profile.

The evidence profile has no novelty on purpose: novelty and the evidence balance pull apart by design. The frontier
profile puts novelty first; its protection against inflated hypotheses is that unknown novelty is drawn over the whole
range (not set high), the balance falls with any data against, and I counts only supported alternatives.

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

**Principle (user decision 2026-11-11): text and numbers are kept apart.** A text cell or paragraph holds words only (the
hypothesis, its origin, what it claims, what changed); a number cell holds one number or one level ("new combination",
"organ / system") and nothing else. Explanations of a number live in its hover note, in the evaluation tab and in the help,
never in the cell. Audit trails (which records were dropped, which rule was checked) live only in the evaluation tab.
Internal codes (profile ids such as "trial-3", indicator codes, module names, prompt versions, method tags in titles) are
never shown; names follow section 10a. Russian only. **A report holds exactly what this section lists**: no columns of
earlier method versions, no axes that left the profiles (non-refutation P, support share, share against), no notes of the
writer's own on records or rules.

**Pool report** (`python -m hyparena.report_v2 prospective --n 60` → `report_<n>_v2.html`; data shaped by
`hyparena/report_v2.py`, page `hyparena/templates/pool_report_v2.html`). A header band (pool title, cut-off date, how many
scored; fixed at the top on a wide screen only) and five tabs, in this order. **Width:** the page uses the width of the
screen: the header band and the content sit in one container `max-w-[1600px] w-full mx-auto` (Tailwind; not `max-w-7xl` or
narrower), wide tables scroll sideways inside their own block, never the page; text blocks inside may stay narrower for
reading. A report written from this manual keeps the same container (an outside report of 2026-11-11 used 1280 px and left
half of a desktop screen empty).

**Short ids.** Every hypothesis has a short id kept in the hypothesis database (`longevity-kg/hypothesis_db/short_ids.jsonl`,
`hyparena/short_ids.py`; user decision 2026-11-11): one numbering for every pool and source, with a leading zero (H01 … H99,
H100 …), given once in the order hypotheses enter the database and never renumbered (the prospective 60 are H01-H60, the
calibration 74 H61-H134). A version adds the letter of its mode to its parent's id (д tuned, с free evolution, н directed
evolution: H49д), and a number from the second version of the same mode on (H49д2). The report reads the ids from the
database, so they do not move when a pool changes; a row without one shows its registry id. The id is shown in every tab
and is searchable. An outside report uses the same ids.

1. **Рейтинг (Ranking).**
   - A switch of the three profiles by their Russian names, and under it one line: "Порядок важности:" followed by the
     profile's indicators in order, ">" between ranks and "=" inside a rank.
   - Filters: origin (all, originals only, versions only), intervention type, search (short id or words of the text).
   - One table, on a phone too: it scrolls sideways inside its frame, the hypothesis column stays fixed. Pages of 15 rows.
   - The **hypothesis cell**: first line the place ("1 место") and the short id; then the hypothesis statement itself (up to
     three lines), under it the registry title in small grey type (one line); a button "текст полностью" expands both; then
     the origin chips (original; tuned; free evolution; directed evolution; "new hypothesis" when a version is far from its
     parent; a warning chip "moved towards the known" when the drift flag is set). The statement opens the card.
   - Then **Балл** (score, two decimals: the third varies by about 0.002 between runs of 10 000 draws, user decision 2026-11-11), **В топ-5** (per cent), and exactly the profile's indicators, one column each in
     the order of importance, each header captioned "ранг важности N" (equal ranks share N). The evidence balance has the
     coverage as a caption ("покрыто 3 из 4"). Every number opens the hypothesis in the evaluation tab.
   - Under the table, the hypotheses not ranked and why (refuted by data; known result; not scored).
2. **Карточки гипотез (Hypothesis cards)**, words only, one collapsible card per hypothesis in the order of the current
   profile:
   - **Текст гипотезы**: the text as submitted (the registry fields as labelled paragraphs).
   - For a version, **Чем отличается от исходной**: the parent with its short id and title, the mode, and the writer's
     description of what was changed.
   - **Как гипотеза понята**: intervention, population, comparator, outcome; **the mechanism step by step**, each step with
     its link type and written as a triple — the subject on a blue plate, the relation in italics with an arrow, the object
     on a sand plate (for a relation whose object is the organism — improves healthspan, extends lifespan, slows ageing — the
     object plate shows what changes, from the claim's measure, with the organism in brackets: "улучшает → физическая
     работоспособность (человек)") (a legend line "что действует / как → / на что" above the list); **the stated experiment** (design,
     control, planned size, primary outcome); **the alternative explanations** as triples.
   - A button "Оценка →" to the same hypothesis in the evaluation tab. No plain-language analysis (user decision 2026-11-11).
3. **Оценка гипотез (Evaluation of hypotheses)**, numbers, one collapsible block per hypothesis in the order of the current
   profile, with a link "← Карточка" back:
   - **Оценка в профилях**: per profile the score (two decimals), the place, the top-5 probability, the room to improve.
   - **Показатели**: evidence balance, coverage, novelty with the paper that sets it (opens the paper card), I, I headroom,
     scope, feasibility, how clinical the endpoint is, role of AI, rising attention, best design for the outcome,
     independent sources for the outcome.
   - For a version, **Сравнение с исходной гипотезой**: a three-column table (indicator; parent → version; what changed),
     the third column written from the values of this pair, never a generic reading — the scores as one line (where they
     rose or fell, and by how much), evidence balance, coverage (how many places the chain gained and how many have data),
     the share of links with support before the cut-off, novelty, I, scope; then "Сдвиг к известному: да / нет" with the
     reason.
   - **Звенья цепочки и записи из статей**: link type; the statement as a triple; F / A; S with its 90% interval (or "нет
     данных"); link novelty; the records as chips (for green, against red, with the weight; hover: the quote; a click opens
     the paper card with the quote, design, n, the side and the hypotheses that use it).
   - **Альтернативные объяснения**: the alternative as a triple; its support in the literature with the papers it rests on
     (chips as for the links, 2026-11-11); under one header "Что делает
     эксперимент" the two columns "при успехе" and "при неудаче".
   - **Флаги** with the concrete reason in this hypothesis, and **Что поднимет оценку**: the improvement list with the
     expected change of the indicators and of the score per profile, and the papers each item rests on.
   - On a phone every table of this tab scrolls inside its own frame.
4. **Схема работы (How it works)**, self-contained: steps 0-11 (hypotheses in; card; search; reading; record weight; link
   strength and evidence balance; novelty; experiment and alternatives; feasibility and the other indicators; ranking;
   improvements and versions; report). Each step says what it does and, under "Как реализовано", what is done by a language
   model (labelled LLM: with which task) and what by code, in plain words: no module names, formulas, ideas or variants not
   implemented. Where details help, a link opens the matching section of the help.
5. **Справка (Help)** in two levels.
   - *First level*, one screen of words: what the report is; how to read the ranking (profiles, score, top-5 probability,
     ranks of importance); how to read a card and its evaluation; what the report does not claim (it is not a forecast of
     the trial; the clean test is the prospective pool).
   - *Second level*, collapsed sections, each a table: **the weight of a record** (factor, what it accounts for, values; the
     null weighted by power; the fold of one paper or trial); **link strength, evidence balance and coverage** (quantity,
     formula, how to read); **reading rules** (situation, how it is read; all seven rules of section 4); **novelty** (level, when); **the experiment, scope,
     feasibility** (indicator, how it is computed, scale); **profiles, ranks of importance and ASPID** (the table of ranks per
     profile, each profile's order, ASPID explained plainly and then formally: scales, weights, the draw, the score, place
     and top-5); **improvements and versions** (term, meaning); **provenance** (cut-off date, method version, scores hash);
     **a glossary** of every parameter shown. Limits and validation status are not in the report's help; they are in this
     manual (section 12) and in `docs/system/`.

Every column header, chip and number has a hover note. Colours carry meaning only for direction (green for, red against),
for warnings (amber) and for the two parts of a triple.

Reports on private hypotheses stay in the private repository (`longevity-kg`).

**A report written by a model from this manual** (section 0) follows the same tabs; for one hypothesis without a pool, the
card (tab 2) and its evaluation (tab 3). The first layout (`python -m hyparena.report_html prospective --n 60`) and the
older one-hypothesis report (`python -m hyparena.analyze`) are kept in the code; the layout of 2026-11-08 is in
`archive/method-history.md`.

## 10a. Names and the help section of a report

A report written outside the code (by an outside reader such as Argon, or by a model from section 0) tends to keep codes
untranslated, coin its own names for the same thing, or shorten the help section. Both make two reports of the same pool
hard to compare (user note 2026-11-09). The code report is the reference; another report follows it:

- **Names.** Use the Russian name of the table below in a Russian report and the English one in an English report. Never
  show a code alone (`chain_state`, `contested_link`); a code may follow the name in parentheses. Do not rename: if a term
  is not in the table, describe it in words and give the code, not a new name. The renamings already made are final:
  "баланс доказательств" (not "состояние цепочки" or "проверенность"), one column "Запас" (room to improve; I headroom only
  in its note).
- **Ids of links and alternatives** (c1, alt2, p3) and link-type codes ("outcome") are never shown: a link is named by its
  triple or its type in words ("звено исхода «приседания — улучшают — SPPB»"). Levels are shown by their names everywhere,
  the version comparison included ("аналог → новый контекст", not "analog → new_context").
- **Flags** (section 9) are shown by their names below, with the link or alternative they concern; the code may follow in
  parentheses.
- **The tabs and the help section** are those of section 10, in that order: the ranking, the hypothesis cards (words
  only), the evaluation of hypotheses (numbers), how it works, and the help in two levels (one screen of words first; then,
  collapsed and as tables, the weight of a record, link strength with evidence balance and coverage, the reading rules,
  novelty, the experiment with scope and feasibility, the profiles with the ranks of importance and ASPID, improvements and
  versions, provenance, a glossary of every parameter shown). A part may be short, but none is left out, and the numbers in
  it are this manual's (section 14). Short ids, triples and the separation of text and numbers follow section 10.
- **Check**: an outside report is read against this table and list before its content is compared with the code report.

The table is the code's own (`hyparena/report_html.py` IND_NAMES, LINK_NAMES, NOVELTY_NAMES, DESIGN_NAMES, DISC;
`hyparena/report_v2.py` FLAG_NAMES, PROFILE_LABEL); `tests/test_manual.py` checks that every entry is here.

| Kind | Code | Russian | English |
|---|---|---|---|
| indicator | `P` | неопровергнутость механизма | non-refutation of the mechanism |
| indicator | `I` | информативность эксперимента | informativeness of the experiment |
| indicator | `I_headroom` | запас информативности | room for a more informative experiment |
| indicator | `W` | размах механизма | scope of the mechanism |
| indicator | `feasibility` | реализуемость | feasibility |
| indicator | `best_design_outcome` | лучший дизайн по исходу | best design for the outcome |
| indicator | `independent_outcome` | независимые источники по исходу | independent sources for the outcome |
| indicator | `against_share` | доля данных «против» | share of evidence against |
| indicator | `endpoint_clinical` | клиничность конечной точки | how clinical the endpoint is |
| indicator | `trend_pubmed` | рост внимания в литературе | rising attention in the literature |
| indicator | `ai_role` | роль ИИ | role of AI |
| indicator | `support_share` | подтверждённость механизма | how much of the mechanism is supported |
| indicator | `chain_state` | баланс доказательств | evidence balance |
| indicator | `N` | новизна | novelty |
| link type | `delivery` | доставка | delivery |
| link type | `engagement` | действие на мишень | target engagement |
| link type | `pathway` | сигнальный путь | pathway |
| link type | `effect` | промежуточный эффект | intermediate effect |
| link type | `outcome` | исход | outcome |
| novelty level | `new_context` | новый контекст | new context |
| novelty level | `translation` | перенос на другой вид | translation |
| novelty level | `analog` | аналог | analog |
| novelty level | `new_mechanism` | новый механизм известного эффекта | new mechanism of a known effect |
| novelty level | `new_combination` | новое сочетание | new combination |
| novelty level | `new_link` | новое звено | new link |
| novelty level | `unknown` | неизвестно | unknown |
| design | `none` | нет данных | no data |
| design | `cells` | клетки | cells |
| design | `animal` | животные | animals |
| design | `observational` | наблюдательное | observational |
| design | `review` | обзор | review |
| design | `non_randomised` | нерандомиз. | non-randomised |
| design | `meta_analysis` | метаанализ | meta-analysis |
| design | `rct` | РКИ | RCT |
| what the experiment does to an alternative (d) | `eliminated` | отсекает | rules it out |
| what the experiment does to an alternative (d) | `weakened` | ослабляет | weakens it |
| what the experiment does to an alternative (d) | `unchanged` | не различает | does not tell apart |
| flag | `build_mechanism` | механизм не выписан | mechanism not written |
| flag | `name_supported_alternatives` | нет подкреплённых альтернатив | no supported alternatives |
| flag | `improve_experiment` | эксперимент оставляет альтернативы | experiment leaves alternatives standing |
| flag | `find_primary_report` | найти статью самого испытания | find the trial's own paper |
| flag | `contested_link` | спорное звено | contested link |
| flag | `retracted_source_dropped` | отозванная статья исключена | retracted paper dropped |
| flag | `established_by_approval` | звено принято по одобрению | link accepted by approval |
| profile | `evidence` | Доказательность | Evidence |
| profile | `funding` | Финансирование | Funding |
| profile | `frontier` | Фронтир | Frontier |

## 11. Improvements and evolution

**The improvement list** (`hyparena/card/improvements.py`) is computed by code from the analysis of each hypothesis and
shown in its report ("What would raise it"). Each item says what to do, which link or alternative it concerns, the facts it
rests on (PMID and quote) and its expected effect: the indicators before and after and the score under each profile before
and after, computed by the same rules with the item done (fixed scales, so the expected score does not depend on the pool).
Items fall into two classes:

| Class | Item | When it appears | Expected effect computed as |
|---|---|---|---|
| fixable by rewriting | experiment_alternatives | supported alternatives the stated experiment leaves standing | I with those alternatives ruled out |
| | rewrite_refuted_link | a link the data are against (S < 0.5) | the balance without the records against (an upper bound) |
| | narrow_population | records for come from an adjacent population, age or sex | the balance with those records in the exact context |
| | write_mechanism | the chain is the outcome only | not computable in advance (depends on what is found) |
| | clinical_endpoint | the endpoint is a biomarker or a self-report | the score with the endpoint "function" |
| needs new data | support_link | a link with weak support (0.5 ≤ S < 5/6) | the balance with the link at 5/6 |
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
`ALLOW_PAID=1` it runs the evolution). The room of every hypothesis of the prospective pool is in its report.

**Evolution** (`hyparena/card/evolve_v3.py`, on request) improves chosen hypotheses and scores the improved versions
the same way as every hypothesis. **Tuning and free evolution are separate, named modes** (user decision 2026-11-07): a
tuned version is the same hypothesis with its fixable defects repaired; a free version may be another hypothesis.

| Mode | Purpose | What the writer may change | Novelty | How the improved version is scored | Report label | Status |
|---|---|---|---|---|---|---|
| tune (доработка), `--mode tune` | repair the "fixable by rewriting" items | only what the items say, from their facts; the parent's new parts (links at "analog" or "new link") must stay | **constraint**: a version that moved towards the known (`novelty_v34.drift`) goes back to the writer with the reason, once (`retries`); if it still drifts it is kept with the flag and "constraint not kept" | the whole pipeline again on the new text, parent's cut-off | "tuned version" | implemented (prompt `evolve_v3/v2`), not yet run; the first run (2026-11-06, `archive/method-history.md`) was this mode before the constraint |
| free (свободная эволюция), `--mode free --profile P --writer F` | get the best hypothesis for the profile P | everything (claim, mechanism, population, outcome, experiment); the writer is told the profile's order and whether novelty comes first; it names the papers it relies on | **flag only**: a move towards the known is shown, not forbidden | the whole pipeline again; the papers it named count only if the verifier finds them with a verbatim quote before the cut-off (named / found are reported); distance from the parent = 1 − Jaccard of content words; above 0.7 the version is marked "new hypothesis after" the parent | "free evolution" (+ "new hypothesis after") | implemented (prompt `evolve_free/v1`), not yet run; for current pools only (the writer knows literature past the cut-off); the user's preferred mode for improving |
| directed (направленная эволюция), `--mode directed --profile frontier` | reach the target of a profile; first frontier: one new link | keep the intervention and every supported link; add exactly one new link between supported neighbours, with an experiment that tests it | **target**: N not lower and, when the outcome has records, at least "new mechanism of a known effect" (v3.9), one link at "new link", no drift, and a PubMed count of the new link's subject and object before T under a threshold (guard against reader misses) | the whole pipeline again, parent's cut-off; failed checks go back to the writer once, then kept with "target not reached" | "directed evolution (frontier)" | specified (`specs/directed-evolution-2026-11-09.yaml`), not implemented; an outside reader's hand run met every target by moves the rules below forbid; checked through Argon |
| controlled | test whether the list predicts the gain | one item at a time | — | the parent's card, records and alternatives are kept; only what the item changes is re-checked | — | planned |

Both modes report, next to the drift flag, the **share of links with support before the cut-off**, parent → child: a version can
keep its novelty level and still be assembled from known pieces; a rise above 0.25 is pointed out in the report.
Choosing whom to improve: `--top K --profile P` (the largest room to improve, below). Tuning: one call writes the text, about
21 calls per improved hypothesis, up to twice that with a retry; free evolution: about the same, with the writer named by
`--writer`.

**Rules every improved version keeps (all modes; user decision 2026-11-09).** They are part of the method, not advice: the
code checks them, and a model or outside reader that evolves a hypothesis from this manual (section 0) applies them the
same way. A version that breaks one is shown with the broken rule, not scored as improved. They come from an outside
reader's hand run of directed evolution (`specs/directed-evolution-2026-11-09.yaml`, `argon_trial_2026_11_09`), where
every target was met by exactly these moves.

1. **Records come only from reading the version.** The version's claims are read again against the papers (and the
   search) before its cut-off; a record is never copied, edited or deleted by the writer. A record against of the parent
   disappears only when the version's claim no longer matches its context by the rules of section 5 (another species,
   population, dose ...), and the report lists every such disappearance with the reason. Upper bounds of the improvement
   list (section 11 above: a rewritten refuted link "scored without its records against") are expectations, never scores of
   a version. Every indicator of a version (balance, coverage, support share, I, scope, novelty, feasibility) is computed on
   the version's own chain and experiment; none is copied from the parent.
2. **Records are not moved between links.** A paper's finding counts on the link whose claim it matches; a writer cannot
   assign it to another link.
3. **Supported links are kept.** Every parent link with S > 1/2 is in the version with the same subject, relation, object
   and qualifiers (directed and tuning modes; free mode reports the change instead).
4. **Scope is not raised by rewording.** W of a version comes from links supported by its own reading; a link rewritten to
   name a hallmark raises W only if its records support the hallmark claim itself.
5. **Narrowing to the found papers is shown.** When a version narrows a claim's context so that records of the parent move
   from adjacent to exact (weight ×2), the report marks the link "fitted to the papers found", lists the records it lifted,
   and the novelty cost is applied (narrowing moves towards the known).
6. **Novelty by absence is counted by code.** The PubMed count that guards a new link uses the link's own subject AND
   object (card labels and synonyms) before T, never a query written by the writer and never a third term (intervention
   form, population, outcome): a conjunction of three narrow terms is empty for almost anything. In the outside reader's
   run, four "0 papers" new links had 19-136 papers on their own subject and object.
7. **A bigger experiment costs feasibility.** Arms, invasive or specialised measures (biopsy, imaging, high-density EMG)
   are part of feasibility (section 8); an experiment that rules out more alternatives by adding arms and measures must
   show its cost. Until feasibility counts them (backlog), the report shows the number of arms and such measures next to I.
8. **A rise in every profile at once is a warning,** not a result: when a version gains in all three profiles with no
   record against left and the room near zero, the report says which of the rules above it was checked against.

**Novelty control** (v3.4, `novelty_v34.drift`, user decision 2026-11-07): a writer model tends to pull a hypothesis towards
what is already known, because that is where the data are. Each pair is flagged **"moved towards the known"** when the
child's novelty N is lower than the parent's (both known), or a link kept in the child (same text) has a lower link level
(for example "only in mice" → "a human trial exists"), or the parent's new link is gone and the child has no new link. The
child is never excluded: it stays in the ranking, and its lower novelty lowers its score where N is an indicator (funding,
frontier). The flag is checked by hand-made drifted pairs (a human trial added on the outcome, a related compound
in place of the intervention's records, the new link removed, a kept link moved down) which must all be flagged, and
controls (an identical child, support added at the same level, a new link added) which must not (`tests/test_v34.py`). In the
first run 1 of 10 pairs was flagged (analog → new context). The improvement item "narrow the population" shows its expected
change of novelty next to its gain, so the cost of narrowing towards the known is visible before it is applied. Since v3.9 the parent and the child are compared with their PubMed counts of new links (`evolve_v3.compare` makes
them when the cut-off is known): a child that loses the parent's "new mechanism of a known effect" is flagged like any other
fall of N (`tests/test_new_mechanism.py`).

**The report section "Evolution"**: a table parent → improved version (evidence balance, I, scope, novelty with the flag, and the
score under each profile, rises in green, falls in red); per pair, collapsed: the items applied, what changed in the text and on which fact,
the expected change of each item against the change obtained, the mechanism links added or removed, the improved text; at
the end, the mean change of the score by kind of item. Hypotheses without an improved version are listed with the reason.
The improved versions also appear in the ranking (section 10).

**Limits.** Evolution in the implemented and controlled modes makes no new evidence: the evidence balance can rise only by moving the
text away from what the data are against or by fitting the text to what was already found (which is exactly the
drift towards the known that the novelty flag shows), and a rise of I is a design that is still to be carried out. The improved text is written from the
findings of the verifier that then scores it (circular), so a rise of the score says what to change, not that the
hypothesis became better. In the free mode new evidence counts only when the verifier finds it; the writer's own knowledge
reaches past the cut-off date, so the free mode is for current pools (scored as of today), not for retrospective samples.
A gap between the expected and the obtained change points at the improvement list (its estimate was wrong) or at the
rewrite (the item was not applied as asked); both are shown. "Needs new data" items are never applied by the first two
modes.

## 11a. Generation and the hypothesis database (specified, not implemented)

**Generation** (`specs/generation-2026-11-09.yaml`, user decision 2026-11-09) is a separate command,
`python -m hyparena.card.generate --mode free|structured|profile --topic ... [--profile P] [--n K] [--writer F] [--as-of T]
[--fields FILE] [--from-texts FILE] [--dry]`. It is evolution without a parent: after the text the pipeline is the same
(card, search before T, reading, alternatives, endpoint, v3.6 rules, ASPID under every profile on fixed scales). The number
of hypotheses and the writer model are parameters; texts written in a chat with an outside model enter through
`--from-texts` and go through the same checks; `--dry` names the calls and the price.

| Mode | The writer gets | Accepted by code when |
|---|---|---|
| free | the topic, T, the hypotheses already in the database on the topic ("do not repeat") | an intervention and an outcome are named; not a duplicate |
| structured | as free, plus the card template (intervention, population, mechanism links, outcome, decisive experiment); fields fixed by the user must be kept | as free, plus every fixed field survives normalisation, the mechanism is written as links, the experiment has a system, a design and an endpoint |
| profile | as structured, plus the profile's order and what raises its top tiers | as structured, plus the profile's target: frontier = the checks of directed evolution (one new link between supported neighbours, PubMed absence count); funding = feasibility and a functional or clinical endpoint; evidence = known records on every link and an experiment that separates the supported alternatives |

**Diversity** is controlled within a run and against the database: typed proximity of the cards (duplicate, variant,
analog, competitor; `hyparena/card/proximity.py`) and text distance; a duplicate is rejected and rewritten once, a duplicate
of a database row is linked to it, not added. Each run reports the share of variant and analog pairs and the number of
distinct interventions and outcomes. With T = today there is no outcome to test against: the outside check (Argon: novel
before T, plausible, testable, on topic, best profile; its grouping against ours) is part of the mode.

**The hypothesis database** (`specs/hypothesis-db-2026-11-09.yaml`) holds every hypothesis version from every source
(registry trials, Bio Arena, other arenas and public sets, our generated and evolved ones), privately in `longevity-kg`:
text, source and terms, author kind (no names), the date written (T of its scoring), parent, outcome if known, the
source's own scores apart from ours, our card, scores with method version and date, the history of re-scorings, and its
cluster. Families are connected components over duplicate, variant and analog; topics are clusters of a text embedding
with a threshold fixed on a hand-checked sample. Scoring runs: the registry rows first (no cost), then Bio Arena (a sample
of 100 by cluster first). The site shows the database with the living arena's re-scoring (method-v3.md section 10); texts
of other authors appear there only with their operators' permission.

Public sets found by the outside reader (Argon pack 14, 2026-11-09, `longevity-kg reviews/argon-2026-11-08/pack_14_answer.json`)
are checked by us before any export; the triage is in the database spec.

## 12. What the method does not do, its known limits and its validation status

- It does not predict whether a trial will succeed; trials are run where support exists but the question is open.
- The verifier keeps about 60% of relevant papers with almost no false ones (measured on three hand-labelled sets): support
  from interventions of the same kind is often missed, so the balance is biased down for programmes and behavioural interventions.
- Abstracts by default; full texts only where a knowledge-graph row says so.
- Alternatives come from a model, not yet from the knowledge graph.
- Novelty depends on the verifier's recall: a paper it missed makes a hypothesis look newer than it is (about 40% of
  relevant papers are missed). Novelty is therefore an upper estimate; the "known result" gate catches only exact matches.
- Novelty is read off the outcome link first; a known effect with a new mechanism is "new mechanism of a known effect" only
  when the new link's PubMed count was made (v3.9): without the count it stays new context.

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
| evidence balance per link | Spearman 0.24 per link, 0.39 per trial; no refuted link called supported | the reader is generous (mean 0.45 vs ours 0.08); we hold 19% of its key papers: 46% were read only for another link of the trial, 31% read without a record (docs/plans/reading-recall-2026-11-08.md) |

**Reader noise.** Reading the same papers again with the same prompt moves the evidence balance of the 59 prospective
trials (Spearman 0.81 between two readings; R2 and R3 do not move): close places in a ranking are within that noise
(specs/record-weight-2026-11-08.yaml, reader_noise_v9_result). Averaging two readings is the remedy where a ranking matters.

**Deferred from the outside review (2026-11-07), each paid or an inflation risk:**
- I depends on alternatives already published, so a new field gets I = 0 even for a well-built experiment. Planned: a
  second half of I for the rigour of the design (controls, blinding, factorial or dose and timing inversion), scored by two
  model families with only agreement counted, since a well-described experiment is cheap to write.
- Opposite effects in different regimes (timing, dose, polarity) are read as a conflict ("contested"). Planned: the regime
  of the intervention in the verifier's extraction, F and A summed only within comparable regimes.
- An unchecked link has no prior (it is left out of the balance). Planned only as a prior from databases by code (target evidence in OpenTargets or
  ChEMBL), in narrow bounds about 0.4–0.6 and after the admission check; never a model's judgement.
- Precision from full texts (PMC open access, numbers only) instead of the constant before the outcome.
**Validation status (2026-11-11).** Each line is a file in `specs/` with its definitions written before the computation.

| Step | Check | Result |
|---|---|---|
| reading: design, n, blinding | against an outside reader (Argon) | 92-96% agreement |
| reading: which papers hold a finding on the link | key papers of an outside reader (pack 8) | 19% held on their link: the bottleneck (`docs/plans/reading-recall-2026-11-08.md`) |
| paper skeleton (read once, match by code and a model) | 200 link-paper pairs of pack 9 | recall 0.52, precision 0.85, direction 9 of 11 (`specs/paper-skeleton-2026-11-09.yaml`) |
| record weight v3.6 | later RCTs and meta-analyses of the same link (R2) | AUC 0.70 vs 0.66 under v3.5 (`specs/record-weight-2026-11-08.yaml`) |
| record weight v3.6 | order of 80 pairs of records by an outside reader (R4) | τ-b 0.10 (v3.5: 0.04) |
| evidence balance | trial outcomes on the calibration pool (R3) | AUC 0.586 (v3.7), in-sample, wide intervals (`specs/empty-slots-2026-11-09.yaml`) |
| the same question asked to two models | trial outcomes, 63 trials the models do not remember | AUC 0.76 vs 0.59 for our P (`specs/llm-consensus-2026-11-07.yaml`): the models' priors beat the literature count; leakage not excluded |
| intervention match: exact / class / category / other (v3.8) | an outside reader, 80 link-finding pairs blind | weighted κ 0.55, stance agreement 0.89 (`specs/intervention-class-2026-11-11.yaml`) |
| I (d of the alternatives) | an outside reader, holdout of 30 trials | κ 0.35 |
| N (novelty) | an outside reader | weighted κ 0.14-0.26; ours is nearer the new |
| prospective pool, 60 ongoing trials | outcomes 2026-11 … 2028-12 | scores frozen 2026-11-06 with a SHA-256 (`specs/prospective-2026-11-06.yaml`): the clean test |

Against trial outcomes the record weights add nothing over counting records (ablation of 2026-11-07, in
`archive/method-history.md`); the weights are kept for what they are for: ordering later trials of the same link (R2) and
telling a large RCT from a cell study in the report. AUC here is the tied AUC between positive and null trials.

## 13. Worked example (computed by the code)

Hypothesis: "x activates AMPK, AMPK suppresses senescent cells (hallmark: cellular senescence), and x improves function in
older adults". Records: two mouse studies for c1 (n = 40 each, large effect, between groups); none for c2; one RCT of 120 for
c3 (medium effect). One proposed alternative with an observational study of 300 for it, cut off by the stated experiment.

| | c1 engagement | c2 pathway | c3 outcome | evidence balance | | I | W | |
|---|---|---|---|---|---|---|---|---|
| v3.7 | S 0.936 (F 1.000) | no record, not averaged | S 0.905 (F 0.839) | evidence balance 0.841 | | 0.581 | organ | |
| v3.7, with one mouse study of 40 for c2 | | S 0.793 | | evidence balance 0.756 | | | | |
| v3.7, with one mouse study of 40 against c2 | | S 0.342 | | evidence balance 0.455 | | | | |

Under v3.7 the empty c2 is not averaged in, so the balance is that of c1 and c3 (0.841, against 0.560 under v3.6, where c2
counted as 0). A mouse study of 40 for c2 then adds a slot weaker than the other two and lowers the balance to 0.756: the
balance says how strong what is known is, and the coverage (2 of 3 slots → 3 of 3) says how much is known.

The RCT of 120 with a medium effect weighs 0.839 (its effect counts in full), each link's S comes from F − A, and a mouse
null of 40 weighs by its power (0.24; preclinical design 1, between groups 1) against 0.5 for the mouse study for.
Novelty: new context (an RCT on the outcome exists). The same example under v3.3-v3.6 is in `archive/method-history.md`.

## 14. Constants (checked against the code)

```yaml
v32:
  c_anchor: 6.666667          # 4 / 0.6
  fold_rest: 0.25
  precision: {floor: 0.25, full_at_n: 300}
  effect_d_full: 0.8
  p_floor_aspid: 0.01
v37:
  empty_slots: skip          # a slot with no record is not averaged into the balance or the support share
v36:
  loglr_lambda: 2.682397     # 2 atanh(2/3) / 0.6
  design_grade3: {rct: 1.0, meta_analysis: 1.0, non_randomised: 0.5, observational: 0.5, other: 0.25}
  effect_full_from: 0.71875  # the continuous effect weight of d = 0.5
meta_certainty: {high: 1.0, moderate: 1.0, low: 0.5, very_low: 0.25, not_reported: 0.75}   # 2026-11-11
v34:
  preclinical_precision: 0.5
  novelty_levels: [new_context, translation, analog, new_mechanism, new_combination, new_link]
feasibility:
  system: {data_analysis: 1.0, cells: 1.0, yeast: 0.9, worm: 0.85, fly: 0.85, mouse: 0.5, rat: 0.5, human: 0.0}
  duration: {weeks: 1.0, months: 0.666667, years: 0.333333, decades: 0.0}
  n_bands: [[50, 1.0], [200, 0.666667], [1000, 0.333333]]   # n under the bound gets the score; more: 0
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
  funding: [[chain_state], [feasibility], [trend_pubmed, ai_role, N], [I, W], [endpoint_clinical, best_design_outcome, independent_outcome]]
  frontier: [[N], [chain_state], [I], [feasibility], [W]]
```

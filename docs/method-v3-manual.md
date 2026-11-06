# Method v3 manual: how a hypothesis is scored and how to read the report

Version: rules **v3.2** as of 2026-11-06 (`hyparena/card/rules_v32.py` on top of `rules_v3.py` variant v3.1 and
`v3_levels.py`), aggregation by ASPID over the axes (`hyparena/card/aspid_v3.py`, `configs/profiles_v3.yaml`). The
specification with its history and decisions is `docs/spec/method-v3.md` (in Russian, sections 9-13); this manual is the
self-contained English description. The constants in section 13 and the numbers of the worked example in section 12 are
checked against the code by `tests/test_manual.py`: if the code changes, the test fails until this manual is updated. The
discrete levels of v3 and v3.1, used by earlier runs and still shown as labels, are in appendix A.

## 0. Using this manual as context

Attach this manual to a hypothesis (and, if available, the literature found for it) and ask for a report in the template of
section 10. Rules for a model writing such a report:

- Score only what the literature you were given says; every record needs a PMID and a verbatim quote. A record you cannot
  quote does not exist.
- Use the scales and formulas of sections 5-7 exactly; show the arithmetic for P, I and V.
- Do not predict the outcome of the trial; P is plausibility of the mechanism given the literature, not a forecast.
- When in doubt between two levels, take the lower one and say why.
- A report written this way is an approximation. The authoritative report is the one the code builds
  (`python -m hyparena.analyze RUN.json`), from the same rules and the records the verifier extracted.

## 1. What is evaluated

A hypothesis is valued for its **mechanism**: a chain of links from the intervention to the outcome. A hypothesis is
promising when the key links are not refuted by current data and the mechanism, if true, would change the question a lot.

The method computes **axes** (what can be checked against the literature) and then ranks hypotheses by **ASPID** under
several **profiles** (whose order of importance says what matters to whoever ranks):

| Axis | Question | Range |
|---|---|---|
| P, plausibility | How well is each link of the chain supported by the literature before the date T? | 0-1, product over links, with a 90% interval |
| I, informativeness | Which supported competing explanations does the stated experiment cut off? | 1/3-1 |
| W, scope | How far does the supported mechanism reach: one condition, an organ or system, a hallmark of ageing? | local, organ, hallmark |
| V, reference | P × I (0 if filtered): the point of equal weights | 0-1 |

**ASPID** (section 8) is the main aggregation: each profile orders the indicators (P, I, scope, feasibility and others) by
importance, weights are drawn at random under that order, and a hypothesis gets an expected value and the probability of
being in the top. A near-zero P is not compensated (P and I are on log scales). V is reported as one reference point, not
as the ranking.

Only P is meant to track trial outcomes; I, W and V describe what a result would teach, whatever it is. Validation status
is in section 11.

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
  is "none".
- A review restating one trial counts as that trial (an RCT of unknown size until the trial's own paper is found).
- **Independence group**: a paper whose abstract names exactly one trial id (NCT, ISRCTN) belongs to that trial; else the
  paper is its own group. Several records of one group count once (section 5).
- Retracted papers weigh nothing (v3.1: also when PubMed itself marks them retracted).

## 5. Weight of a record

`w = design × precision × effect × comparison × context`.

| Factor | v3.2 | |
|---|---|---|
| design, claim about humans (outcome link) | cells, animal, observational, review, non-randomised, meta-analysis, RCT | 1/7 … 7/7 |
| design, every link before the outcome, or a claim about animals | cells, review, primary study | 1/3, 2/3, 1 |
| precision | min(1, ln n / ln 300), at least 1/4; unknown n = 1/4 | continuous |
| effect | where the phrase gives a ratio or a standardised difference: d = abs(ln ratio) × √3 / π or abs(d), weight 1/4 + 3/4 × min(1, d / 0.8); otherwise the rule-A class: none, small, medium, large = 1/4 … 4/4, unclear 1/2 | continuous or class |
| comparison | none, within group, between groups | 1/3, 2/3, 1 |
| context | same class of intervention, adjacent population or species, exact | 1/3, 2/3, 1 |

A record against (a null or opposite result from a comparison) takes the top effect weight: a clear null weighs like a
clear positive. A record about another intervention altogether weighs 0. Retracted papers weigh 0.

**Folding by independence group.** On each side (for, against) the records of one group are folded: the heaviest counts
fully, every further record of the group with 1/4. F and A are the folded sums.

The distance to the clinic is charged once: links before the outcome use the preclinical design scale, the outcome link the
clinical one; the context factor still charges another species or population on every record.

## 6. Strength of a link and the gate

F = folded weight of the records for, A = against.

**Strength** S = (cF + 1) / (c(F + A) + 2), the mean of Beta(1 + cF, 1 + cA), with c = 4 / 0.6, so that F = 0.6 with
nothing against gives 5/6 (the old "moderate"). Its 90% interval comes from the Beta quantiles. Reading S:

| Situation | S | Interval |
|---|---|---|
| no record | 0.5 | wide (0.05-0.95): nothing is known |
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

- **P** = product of S over the links, with a 90% interval from the links' intervals. Parallel outcomes (mass, strength,
  function) count once: the one matching the primary outcome of the stated experiment, else their mean. Consecutive pathway
  links (a cascade written as several steps) are one slot, their geometric mean. A long unsupported chain gets a low P by
  construction (four links without records: 0.5^4 ≈ 0.06), and a wide interval: little is known about it.
- **W, scope**, from supported links only: a hallmark of ageing (needs a link at least moderate), an organ or system, else
  local. A scope that is claimed but not supported counts as local. An indicator of ASPID, not a factor of V.
- **I** = 1/3 + 2/3 × min(1, Σ a·d / 1.5) over the proposed alternatives. a = support of the alternative, max(0, 2 (S − 0.5))
  with S its strength; d = what the stated experiment does to it at either outcome (cut off 1, weakened 0.5, unchanged 0).
  Without supported alternatives I = 1/3: an invented alternative adds nothing.
- **V** = P × I (0 if filtered). **Headroom I** = I if the experiment cut off every supported alternative (d = 1): what
  improving the experiment could add.

Protections against inflated hypotheses, by construction: the product over links; alternatives without support weigh 0;
scope only from supported links; records of one trial or paper count once.

## 8. ASPID: indicators and profiles

Values sit on fixed scales, so a hypothesis's expected value does not depend on the rest of the pool. An unknown value is
drawn over its whole range in every draw.

| Indicator | What it says | Scale |
|---|---|---|
| P | plausibility of the chain | log, from 0.01 |
| I, I_headroom | informativeness of the stated / of an improved experiment | log, 1/3-1 |
| W | scope | local < organ < hallmark |
| feasibility | system, duration, planned n, readiness of the intervention (approved or not a compound 1, in trials 0.5, neither 0) | 0-1 |
| best_design_outcome | best design among the records of the outcome link | cells … RCT |
| independent_outcome | independent sources for the outcome link | 0-5 |
| against_share | share of the chain's weight against | 0-1, lower better |
| endpoint_clinical | how close the trial's primary endpoint is to a clinical outcome (two model families agree, else unknown) | biomarker < patient-reported < function < clinical event |
| trend_pubmed | rising attention: PubMed records on the intervention in the last 3 years vs the 3 before, net of PubMed's growth | -0.5 … 1.5 |
| ai_role | role of AI in the hypothesis | none < analysis < in the loop < AI is the intervention |

| Profile | Order of importance (tiers) |
|---|---|
| evidence | P > I > W > {best design, independent sources, share against, endpoint} |
| evolution | headroom I > P > W > {best design, independent sources, share against} |
| funding | P > feasibility > I > W > {best design, independent sources, share against, endpoint} |
| investor (draft) | P > {trend, AI role} > feasibility > {I, endpoint} |

A new indicator enters only when it passes four conditions, checked on saved data before it is used: reliable (computed by
code, or extracted with a verbatim phrase and agreed by two model families, κ ≥ 0.6); separating (at least three values,
none above 70%); not redundant (|Spearman| < 0.7 with the existing indicators); its own question. Rejected so far:
four-axis indirectness (redundant), estimand completeness (unreliable), genetic support of the target (too few values on
registry trials), trial-registry trend (adds nothing).

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

## 10. Report template

Every report on one hypothesis, by code or by a model, has these sections:

1. **Summary**: P with its interval, I, scope, V, gate; place under each ASPID profile if there is a pool.
2. **Mechanism chain**: one row per link: id, type, claim, S with its interval, label, F / A, the main records (PMID, for
   or against, weight, design, n, effect).
3. **Why this score**: what raises it (the strongest links, the indicators above the pool's middle) and what lowers it
   (the weakest link, the indicators below); what W rests on; the alternatives (a, d).
4. **What to improve**: concrete actions, each with the score it would give where the rules allow computing it: support
   the weakest link (what kind of evidence would raise it), improve the experiment (headroom), the flags turned into actions.
5. **Limitations**: of the method and of this run (section 11).
6. **Provenance**: date T, configuration, models, number of calls, rules version, hash of the scores if frozen.

## 11. What the method does not do, its known limits and its validation status

- It does not predict whether a trial will succeed; trials are run where support exists but the question is open.
- The verifier keeps about 60% of relevant papers with almost no false ones (measured on three hand-labelled sets): support
  from interventions of the same kind is often missed, so P is biased down for programmes and behavioural interventions.
- Abstracts by default; full texts only where a knowledge-graph row says so.
- Alternatives come from a model, not yet from the knowledge graph.

**Validation status (2026-11-06).**

| Check | Result |
|---|---|
| extraction of design, comparison, n (three hand-labelled sets) | passed each time (0.81-0.96) |
| effect class (rule A) | passed formally (most effects "unclear") |
| P vs trial outcome, calibration (30 trials, seen while building v3) | v3 0.677, "unclear"; v3.2 0.65 |
| P vs trial outcome, fresh sample 2023-2026 (14 decisive) | v3 0.571 "unclear"; v3.2 0.61 (not pre-registered) |
| P vs trial outcome, fresh sample 2000-2022 (26 decisive) | v3 0.534 "no signal"; v3.2 0.64 (not pre-registered) |
| prospective pool: 60 ongoing trials ending 2026-11 … 2028-12 | scores frozen 2026-11-06 with a SHA-256 (`specs/prospective-2026-11-06.yaml`); the clean test of v3.2, when the trials report |

AUC is the tied AUC of P between positive and null trials; the pre-set rule is "signal" at ≥ 0.60 with the lower bound of
the 95% interval above 0.45, "no signal" below 0.55. The samples are small and the intervals wide.

## 12. Worked example (computed by the code)

Hypothesis: "x activates AMPK, AMPK suppresses senescent cells (hallmark: cellular senescence), and x improves function in
older adults". Records: two mouse studies for c1 (n = 40 each, large effect, between groups); none for c2; one RCT of 120 for
c3 (medium effect). One proposed alternative with an observational study of 300 for it, cut off by the stated experiment.

| | c1 engagement | c2 pathway | c3 outcome | P [90%] | I | W | V |
|---|---|---|---|---|---|---|---|
| v3.2 | S 0.906 (F 1.293) | S 0.5, no record | S 0.839 (F 0.63) | 0.380 [0.021; 0.936] | 0.651 | organ | 0.247 |
| with one mouse study of 40 for c2 | | S 0.842 | | 0.639 | | organ | 0.416 |

The wide interval of P comes from c2: a link with no record could be anything. The report points at c2 as the link to
support; one mouse study would raise V from 0.25 to 0.42.

## 13. Constants (checked against the code)

```yaml
v32:
  c_anchor: 6.666667          # 4 / 0.6
  fold_rest: 0.25
  precision: {floor: 0.25, full_at_n: 300}
  effect_d_full: 0.8
  p_floor_aspid: 0.01
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
  evidence: [[P], [I], [W], [best_design_outcome, independent_outcome, against_share, endpoint_clinical]]
  evolution: [[I_headroom], [P], [W], [best_design_outcome, independent_outcome, against_share]]
  funding: [[P], [feasibility], [I], [W], [best_design_outcome, independent_outcome, against_share, endpoint_clinical]]
  investor: [[P], [trend_pubmed, ai_role], [feasibility], [I, endpoint_clinical]]
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

# Method v3 manual: how a hypothesis is scored and how to read the report

Version: rules v3 and v3.1 as of 2026-11-05 (`hyparena/card/rules_v3.py`, `hyparena/card/v3_levels.py`). The specification with
its history and decisions is `docs/spec/method-v3.md` (in Russian); this manual is the self-contained English description.
The numbers in section 11 are checked against the code by `tests/test_manual.py`: if the code changes, the test fails until
this manual is updated.

## 0. Using this manual as context

Attach this manual to a hypothesis (and, if available, the literature found for it) and ask for a report in the template of
section 9. Rules for a model writing such a report:

- Score only what the literature you were given says; every record needs a PMID and a verbatim quote. A record you cannot
  quote does not exist.
- Use the scales and thresholds of sections 5-7 exactly; show the arithmetic for P, W, I and V.
- Do not predict the outcome of the trial; P is plausibility of the mechanism given the literature, not a forecast.
- When in doubt between two levels, take the lower one and say why.
- A report written this way is an approximation. The authoritative report is the one the code builds
  (`python -m hyparena.analyze RUN.json`), from the same rules and the records the verifier extracted.

## 1. What is evaluated

A hypothesis is valued for its **mechanism**: a chain of links from the intervention to the outcome. A hypothesis is
promising when the key links are not refuted by current data and the mechanism, if true, would change the question a lot.

Three axes and their product:

| Axis | Question | Range |
|---|---|---|
| P, plausibility | How well is each link of the chain supported by the literature before the date T? | 0-1, product over links |
| W, scope | How far does the supported mechanism reach: one condition, an organ or system, a hallmark of ageing? | 1/3, 2/3, 1 |
| I, informativeness | Which supported competing explanations does the stated experiment cut off? | 1/3-1 |
| V, promise | P × W × I | 0-1 |

Feasibility (cost, duration, sample size, readiness of the intervention) is a separate tier, used to break near ties, not a
factor of V. Only P is meant to track trial outcomes; W, I and V describe what a result would teach, whatever it is.

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
- Retracted papers weigh nothing (v3.1: also when PubMed itself marks them retracted).

## 5. Weight of a record

`w = design × precision × effect × comparison × context`, each factor a level of its scale. A scale with k ordered levels
gives level i the weight i/k (equal steps; departures only when calibration shows they break something).

| Factor | Levels, lowest first | Weights |
|---|---|---|
| design, claim about humans | cells, animal, observational, review, non-randomised, meta-analysis, RCT | 1/7 … 7/7 |
| design, claim about animals (v3.1: also every link before the outcome) | cells, review, primary study | 1/3, 2/3, 1 |
| precision (n of the finding) | unknown or < 30, 30-99, 100-299, ≥ 300 | 1/4 … 4/4 |
| effect | none, small, medium, large; unclear = 0.5 | 1/4 … 4/4 |
| comparison | none, within group, between groups | 1/3, 2/3, 1 |
| context | same class of intervention, adjacent population or species, exact | 1/3, 2/3, 1 |

A record against (a null or opposite result from a comparison) takes the top effect level: a clear null weighs like a clear
positive. A record about another intervention altogether weighs 0.

In v3.1 the distance to the clinic is charged once: links before the outcome use the preclinical design scale, the outcome
link the clinical one; the context factor still charges another species or population on every record.

## 6. Strength of a link and the gate

F = summed weights of the records for, A = against.

| Level | Rule | Weight S (v3) | Weight S (v3.1) |
|---|---|---|---|
| refuted | strong refutation (gate) | 1/6 | 1/6 |
| contested | A > 0 and A ≥ F/2 | 2/6 | 3/6 |
| unverified | no usable record | 3/6 | 2/6 |
| weak | 0 < F < 0.6 | 4/6 | 4/6 |
| moderate | F ≥ 0.6 | 5/6 | 5/6 |
| strong | F ≥ 1.5 and at least two independent sources | 1 | 1 |

Reference points: one RCT with ≥ 300 participants, a large between-group effect and the exact population weighs 1.0; one
RCT of 120 with a medium effect weighs about 0.56; a mouse study with unknown n, an unclear effect, a between-group comparison and another species (context 2/3)
weighs 0.024 for a link about humans in v3, 0.083 in v3.1 (before the outcome link).

**Approved action.** An engagement link whose subject is one approved drug (ChEMBL phase 4) is taken as moderate without
search. v3: any approved drug with a known mechanism; v3.1: only when one of the drug's ChEMBL targets is named in the link.

**Gate (the only filter).** A key link is refuted when there is a record against of the top design (RCT or meta-analysis),
between groups, in the hypothesis's population, and no record for of that level. Then V = 0. Nothing else filters: an
undeveloped but promising hypothesis keeps its score and gets flags.

## 7. Axes

- **P** = product of S over the links. Parallel outcomes (mass, strength, function) count once: the one matching the primary
  outcome of the stated experiment, else their mean. v3.1: consecutive pathway links (a cascade written as several steps) are
  one slot, their geometric mean. A long unsupported chain gets a low P by construction (four unverified links in v3:
  (1/2)^4 ≈ 0.06).
- **W**, from supported links only (at least weak): a hallmark of ageing 1, an organ or system (any supported engagement,
  pathway or effect link) 2/3, else local 1/3. v3.1: the hallmark level needs a link at least moderate. A scope that is
  claimed but not supported counts as local.
- **I** = 1/3 + 2/3 × min(1, Σ a·d / 1.5) over the proposed alternatives with support. a = support of the alternative (v3:
  its link weight; v3.1: weak 1/3, moderate 2/3, strong 1); d = what the stated experiment does to it at either outcome
  (cut off 1, weakened 0.5, unchanged 0). Without supported alternatives I = 1/3: an invented alternative adds nothing.
- **V** = P × W × I (0 if filtered). **Headroom V** = V if the experiment cut off every supported alternative (d = 1): what
  improving the experiment could add.

Protections against inflated hypotheses, by construction: the product over links; alternatives without support weigh 0;
scope only from supported links.

## 8. Flags (inputs for improving the hypothesis)

| Flag | Meaning |
|---|---|
| build_mechanism | no engagement, pathway or effect link: the mechanism is not written |
| name_supported_alternatives | no proposed alternative has support |
| improve_experiment | supported alternatives are left standing by the stated experiment (headroom above V) |
| find_primary_report | a review restates a trial whose own paper was not found |
| contested_link | a link has records for and against of comparable weight |
| <id>_established_by_approval | a link was taken as moderate by the approved-action rule |
| retracted_source_dropped | (v3.1) a retracted paper was found and given no weight |

## 9. Report template

Every report, by code or by a model, has these sections:

1. **Summary**: V (P × W × I), gate, headroom V, place in the pool if there is one.
2. **Mechanism chain**: a table, one row per link: id, type, claim, level and S, F / A, the main records (PMID, for or
   against, weight, design, n, effect).
3. **Why this score**: the weakest link and its records; what W rests on; the alternatives table (a, d, level).
4. **What to improve**: concrete actions, each with the V it would give where the rules allow computing it: support the
   weakest link (what kind of evidence would raise it), improve the experiment (headroom), the flags turned into actions.
5. **Limitations**: of the method and of this run (section 10).
6. **Provenance**: date T, configuration, models, number of calls, rules variant.

## 10. What the method does not do, and its known limits

- It does not predict whether a trial will succeed; trials are run where support exists but the question is open.
- The verifier keeps about 60% of relevant papers with almost no false ones (measured on three hand-labelled sets): support
  from interventions of the same kind is often missed.
- Abstracts by default; full texts only where a knowledge-graph row says so.
- Alternatives come from a model, not yet from the knowledge graph.
- Validation status (2026-11-05): v2 showed no signal on 30 calibration trials (tied AUC 0.46); v3 has not been run on them
  yet; extraction of design, comparison and n passed on three hand-labelled sets, effect class only formally.

## 11. Worked example (computed by the code)

Hypothesis: "x activates AMPK, AMPK suppresses senescent cells (hallmark: cellular senescence), and x improves function in
older adults". Records: two mouse studies for c1 (n = 40 each, large effect, between groups); none for c2; one RCT of 120 for
c3 (medium effect). One proposed alternative with an observational study of 300 for it, cut off by the stated experiment.

| | c1 engagement | c2 pathway | c3 outcome | P | W | I | V |
|---|---|---|---|---|---|---|---|
| v3 | weak (F 0.286) | unverified | weak (F 0.562) | 0.222 | 2/3 | 0.704 | 0.104 |
| v3.1 | moderate (F 1.0) | unverified | weak (F 0.562) | 0.185 | 2/3 | 0.630 | 0.078 |

In v3.1 the mouse studies count fully for the engagement link, but the unverified pathway link now weighs 2/6 instead of 3/6,
so V is lower: the report points at c2 as the link to support (V would be about 0.29 with c2 moderate, the scope rising to the
hallmark level).

## 12. Constants (checked against the code)

```yaml
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
```

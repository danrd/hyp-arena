# Record weight and the fold of for / against: a step-by-step check (plan, 2026-11-08)

Status: agreed with the user 2026-11-08 (answers below). Definitions, references and the menu of variants are fixed in
`specs/record-weight-2026-11-08.yaml` before any value of steps 3-7 is computed. Free: no model calls (PubMed E-utilities
for dates and abstracts are free and public).

## Question

The weight of a record, `w = design × precision × effect × comparison × context`, and the fold of the weights into a link
state, `S = (cF + 1) / (c(F + A) + 2)`, decide everything above them. Against trial outcomes the weights add nothing over
counting records (ablation, 2026-11-07), but that label is noisy. The check asks, against cleaner references:

1. Which factors are needed, and are there missing ones?
2. Which levels inside each factor (ranks) do the data support?
3. How much each factor weighs (what matters more)?
4. How to fold the records for and against into one link state?

The result must be explainable (each factor and level justified) and must not make quality noticeably worse.

## Decisions of the user (2026-11-08)

1. **Normative frame: GRADE.** Every factor and level is explained through a GRADE domain (study design as the starting
   level, risk of bias, inconsistency, indirectness, imprecision, publication bias; rating up for a large effect). The data
   only choose between variants written in advance.
2. **Quality.** Main references R1 (meta-analysis verdict) and R2 (later trials of the same link); R3 (trial outcomes) is a
   constraint: AUC of the chain state not lower than the current one minus 0.03.
3. **Menu, not fitting.** Variants are written before computing; no free fitting of exponents.
4. **Fold.** Replacing the Beta pseudo-counts by a sum of log likelihood ratios is acceptable if it is not worse.
5. **Pairs of records (R4)** go to Argon (pack 5), from the prospective pool only (the 74 calibration trials are no longer
   used for blind checks with Argon).
6. Push to `main`.

## Map of GRADE domains to the record weight

| GRADE domain | In the method | Status |
|---|---|---|
| study design (starting level) | design | present |
| imprecision | precision (n); for a null, the power of the study (v3.5) | present |
| indirectness | context (same class, adjacent population or species, exact) | present |
| rating up: large effect | effect | present |
| risk of bias | comparison (within / between groups) covers a part; blinding, placebo, open label are absent | **gap** |
| inconsistency | the fold of for / against (implicit) | implicit |
| publication bias, dose-response | absent | absent |

## Steps

| Step | What | Output |
|---|---|---|
| 0 | spec: references, menu, decision rules | `specs/record-weight-2026-11-08.yaml` |
| 1 | descriptive: levels of each factor, share of the spread of log w, correlations, missing values | spec `step1`, `calibration/record_weight_step1.json` |
| 2 | reliability of extraction per factor: earlier gold numbers + a hand check of the context label on 40 records | spec `step2`, `calibration/record_weight_context_check.jsonl` |
| 3 | build R1 and R2 (dates from PubMed), their size and noise | spec `step3` |
| 4 | each factor: drop / flatten / coarsen, on R1-R3 and the movement of link order | spec `step4` |
| 5 | levels inside factors (ranks); R4 where available | spec `step5` |
| 6 | candidate new factors (risk of bias first) | spec `step6` |
| 7 | the fold: Beta (current), log-likelihood sum, best evidence, count difference; the fold by independence group | spec `step7` |
| 8 | decision; manual section "why each factor and level"; KB notes 7s; tests | manual, spec, KB |

After steps 2 and 4: a short report to the user and a decision whether to go on.

## Pack 5 for Argon (R4), prepared in parallel

About 80 pairs of records of one link from the prospective pool, stratified by the factor in which the two records differ
(design, precision, effect, comparison, context) and by the difference of weights, near-ties included; 15 pairs shown
twice in another order (repeatability). Question: which record supports or refutes the claim more strongly (or equal),
with a reason from a closed list. Quotes of abstracts go only to `longevity-kg`.

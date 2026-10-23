# Hypothesis card: specification v1 (MVP)

> Source of truth for the card format and for the **relation vocabulary shared with the knowledge graph** (the knowledge-graph design). Decisions confirmed on 2026-10-15 (see [design notes](working-notes.md), section 5c). Worked examples: [card examples](hypothesis-card-examples.md).
> The code implements this as Pydantic models (single source of truth), exported to JSON Schema; YAML for people.

---

## 1. Principles

1. **Two layers, never mixed.** The *declared* layer comes only from the hypothesis text (normalizer). The *verified* layer is produced by the pipeline (verifier). Ranking reads only the verified layer; judge packets show declared and expert content only labelled as such.
2. **Unestablished ≠ default.** A field is either filled from the text / a source or is `unknown`. No guessed defaults.
3. **Every status carries evidence.** A claim status other than `unverified` or `unresolved` requires at least one evidence record with a verbatim quote (or an executed test); for a contrast outcome (section 7) the record may sit on the referenced alternative.
4. **Necessary-condition checks refuse, never confirm.** They can mark a claim as violating something; they cannot make it `supported`.
5. **Ordinal, not pseudo-probabilities.** Statuses and evidence-profile values are categories.

## 2. Decisions (confirmed 2026-10-15)

| # | Decision |
|---|---|
| 1 | **Atomic claim** = one relation, one context set (species, strain, sex, tissue, dose, age at start), checkable by one source type. |
| 2 | **Closed relation vocabulary** (section 5), plus `other` with a flag; `other` is ignored by symbolic checks. |
| 3 | **The normalizer always builds the claim graph**, also for hypotheses generated inside the system. A generator writes only narrative and, optionally, PICO. |
| 4 | **Biomarker hypotheses**: no separate schema; `hypothesis_type: biomarker` and relation `predicts`. |
| 5 | **Storage**: Pydantic models → JSON Schema; YAML for people. |
| 6 | **Strict admission** (2026-10-18): a hypothesis is something for which a decisive experiment can be defined. Missing critical fields → refinement loop, not ranking; unfalsifiable → stored as a direction (section 4a). |

## 3. Objects

| Object | Written by | Contents |
|---|---|---|
| `RawHypothesis` | external source or internal generator | `id`, `origin: external \| internal \| expert`, `text`, `received_at`, optional `generator`, optional `parent_id` (refined variant of another hypothesis, section 4a) |
| `Admission` | validator (code) | `accepted \| needs_refinement \| not_a_hypothesis`, missing critical fields, `context_specificity`, `known_result: yes \| no` (section 4a) |
| `HypothesisCard` (declared) | normalizer | fields of section 4; claims and edges **without statuses** |
| `VerificationResult` | verifier | per claim: status, evidence, counterevidence, refusals; computed evidence profile (section 8) |
| `JudgePacket` | assembler (view) | card fields + verified claims with statuses and short quotes; generator identity hidden; declared self-assessments (novelty, impact) shown only as "declared", never as facts |

## 4. HypothesisCard (declared layer, MVP)

```yaml
id: H-0001
raw_id: R-0001
hypothesis_type: interventional      # interventional | mechanistic | biomarker | observational
claim_plain: >-                       # one sentence, no jargon (Heilmeier Q1)
  ...
pico:                                 # interventional: required; others: fill what applies, else unknown
  population: {taxon: "NCBITaxon:9606", label: human, strain: unknown, sex: unknown, age_at_start: "older adults"}   # age_at_start: age of the population when the intervention starts (label or value)
  intervention:                       # list: 1 item, or several for a combination
    - {type: compound, label: rapamycin, id: "CHEBI:9168", regimen: "weekly low dose", route: oral}   # type: compound | gene | diet | procedure; route: diet | water | oral | injection | topical | other | unknown (diet/water = mixed into food or drinking water)
  comparator: {type: placebo, label: placebo}   # type: placebo | untreated | standard_care | wild_type | monotherapy | active_drug | chronological_age | other; or unknown
  outcome: {endpoint: healthspan, metric: unknown}   # endpoint: lifespan | healthspan | biomarker | disease | mechanism
  time: unknown
claims:                               # 1..8 atomic claims (section 6)
  - id: c1
    subject: {label: ..., id: ...}    # id optional at normalization; resolved later
    relation: ...                     # section 5
    object: {label: ..., id: ..., hallmark: ...}   # hallmark: one of 12 or omitted
    qualifiers: {species: ..., strain: ..., sex: ..., tissue: ..., dose: ..., age_at_start: ..., comparator: ..., direction: ..., measure: ..., contrast: ...}   # measure: what is measured (healthspan, aging changes); contrast: id of a rejected declared alternative (section 6)
    inherited_from_pico: [species]    # optional; qualifiers copied from PICO, not stated in the claim's span (section 9)
    role: outcome                     # premise | mechanism | analog | outcome | translation
    source_span: "..."                # verbatim fragment of the hypothesis text this claim comes from
edges:                                # between claims
  - {from: c1, to: c2, type: requires}    # requires | supports_if_true | analog_of | contradicts; "c1 requires c2" = c1 holds only if c2 holds; "c1 supports_if_true c2" = if c1 holds, it supports c2
declared_novelty: "..."               # what the source says is new, or unknown (Heilmeier Q3 / NIH Innovation)
decisive_experiment:                  # what would settle the outcome claim (Heilmeier Q8)
  system: human                       # cells | worm | fly | mouse | rat | human | data_analysis
  endpoint: ...
  duration_class: years               # weeks | months | years | decades
declared_alternatives:                # only if the text names them (section 8c); structured like claims
  - id: a1
    subject: {label: ...}
    relation: ...                     # section 5
    object: {label: ...}
    qualifiers: {species: ...}
    inherited_from_pico: [species]    # optional; same rules as for claims (section 9)
    source_span: "..."                # verbatim
    stated_as: rejected               # rejected (contrast "mainly X, not Y": verified, section 7) | listed (never scored)
declared_decision_criteria: "..."     # only if the text states them; shown as "declared", never scored
risks: [...]                          # free text items, or empty list (Heilmeier Q5)
```

Rules:
- Exactly one claim has `role: outcome` (the root claim of the hypothesis).
- `source_span` is mandatory: every claim must be traceable to the hypothesis text. Claims the normalizer infers but the text does not state are **not allowed** in the declared layer (the verifier may add analogs later in its own layer).
- Max 8 claims in MVP; if the text implies more, keep the outcome claim and the most load-bearing links.

## 4a. Admission: what counts as a hypothesis (agreed 2026-10-18)

**Definition.** A hypothesis is a statement for which a decisive experiment can be defined (system, endpoint, duration class). Anything else is a *direction* ("target X is worth studying"): stored, not ranked. Reason: the path to a human test (`path_to_human`, section 8a) and the decisive experiment cannot be defined without the critical fields.

**Critical fields by type** (checked on the declared card, after normalization):

| Type | Required | Desirable (counted in `context_specificity`, not blocking) |
|---|---|---|
| interventional | `pico.intervention` (≥1), `pico.population` with species or human population, `pico.outcome.endpoint` | dose/regimen, sex, age at start, comparator |
| mechanistic | subject entity or intervention, the effect being explained, ≥1 `mechanism` claim or an outcome claim with `qualifiers.contrast` (the asserted explanation) | context as for interventional |
| biomarker | marker, predicted outcome (`predicts` claim), population | comparator (usually chronological age) |
| observational | exposure or variant, outcome, population | design, cohort |

Requiring species removes most of the "vague context matches everything" problem: an unknown species used to match evidence from any organism.

**Three outcomes:**
1. `accepted`: all critical fields present → verification and ranking.
2. `needs_refinement`: critical fields missing but the statement can be made concrete → refinement loop (Co-Scientist's Evolution step plays the same role).
3. `not_a_hypothesis`: outcome not measurable or statement not falsifiable ("X is good for health") → stored as a direction with the reason.

**Refinement rules:**
- A refined version is a **new** `RawHypothesis` with `origin: internal` and `parent_id`; the parent's declared layer is never edited (layer separation holds).
- One vague hypothesis may yield several variants (e.g., "female mice from 20 months", "older adults"); each is evaluated separately. Comparing them shows which concretization is better supported and cheaper to test.
- **Known-result check.** If a variant's outcome claim exactly matches an already `supported` finding (same intervention, species, sex, age, dose), it is marked `known_result`: zero novelty, ranked separately. Strain is part of the match when the card specifies it (agreed 2026-10-20): a finding in another strain of the same species is not a known result; it gives novelty level `new_context` (section 8a). This blocks refinement from drifting towards whatever is already in the literature.
- Refinement cost counts towards the system budget in comparisons with baselines (baselines rank hypotheses as-is).
- **MVP (agreed 2026-10-21):** variants are not generated yet. A `needs_refinement` hypothesis is never dropped silently: it goes to an "awaiting refinement" list together with `missing_critical`. Variant generation comes later as part of the evolution step. Backtests do not need it (template hypotheses are concrete); external pools (e.g. hypotheses parsed from Bio Arena) do.

**`context_specificity`**: number of desirable context fields the hypothesis itself specifies (of species, sex, age at start, dose/regimen, comparator). Shown next to statuses; aggregation may use it. Unspecified non-critical fields still match any value in evidence (`n/a` in `qualifiers_match`, section 7), so specificity makes that leniency visible.

## 5. Relation vocabulary (closed, shared with the KG)

| Relation | Subject → object | Meaning |
|---|---|---|
| `extends_lifespan_in` | intervention → organism | increases mean/median/max lifespan |
| `shortens_lifespan_in` | intervention → organism | decreases lifespan |
| `no_lifespan_effect_in` | intervention → organism | tested, no significant effect |
| `slows_aging_in` | intervention → organism | delays age-related changes not specific to one disease (non-neoplastic pathology, functional decline); object = organism, the measured changes go to `qualifiers.measure` (added 2026-10-19) |
| `improves_healthspan_in` | intervention → organism | improves a healthspan measure (`qualifiers.measure`) |
| `changes_biomarker` | intervention → biomarker | changes a biomarker (direction in qualifiers) |
| `predicts` | biomarker → outcome | biomarker value predicts an outcome (biomarker hypotheses) |
| `inhibits` / `activates` | entity → molecular target | direct target engagement |
| `increases_expression` / `decreases_expression` | entity → gene/protein | expression change |
| `promotes` / `suppresses` | entity/process → process/phenotype | causal up/down effect on a process, cell population or phenotype |
| `part_of` | entity → pathway/process | membership |
| `associated_with` | any → any | association without causal claim |
| `affects_hallmark` | entity/process → hallmark | one of the 12 hallmarks; direction in qualifiers |
| `translates_to` | finding in species A → species B | explicit cross-species transfer (low-trust link) |
| `other` | any → any | flagged; ignored by symbolic checks |

**`other` on the outcome claim** (agreed 2026-10-21). An outcome with `other` would get `unresolved`, hence no `effect_level`, and the hypothesis would sink to the bottom because of a gap in our vocabulary rather than its own weakness. Instead:
1. The normalizer re-parses the hypothesis once, with a hint listing the nearest vocabulary relations.
2. If the outcome is still `other`, the hypothesis gets the flag `unmapped_relation` and goes to an "unparsed" list: not ranked, visible to the expert, its share reported as a pipeline metric.
3. Frequent `other` notes in that list are candidates for extending the vocabulary.

Not `needs_refinement`: refinement changes the hypothesis's content, while here the content may be fine and the gap is ours. `other` on premise or mechanism claims stays as before: `unresolved`, ignored by symbolic checks.

Hallmarks enum (López-Otín 2023): genomic_instability, telomere_attrition, epigenetic_alterations, loss_of_proteostasis, disabled_macroautophagy, deregulated_nutrient_sensing, mitochondrial_dysfunction, cellular_senescence, stem_cell_exhaustion, altered_intercellular_communication, chronic_inflammation, dysbiosis.

## 6. Atomicity: how to split

- One relation per claim: "rapamycin inhibits mTORC1 and reduces senescence" → two claims.
- One context per claim: "extends lifespan in mice and flies" → two claims (different species).
- Mechanism chains are separate claims linked by `requires`.
- A cross-species step is its own claim with `translates_to` or `role: translation`.
- Do not split qualifiers of the same observation (sex, dose stay in one claim unless the text gives different effects).
- Combination claims: list all components in `pico.intervention`. A synergy claim ("better than each alone") is a separate claim with `comparator: monotherapy`.
- **Contrast "mainly X, not Y"** (agreed 2026-10-19): the point of such a hypothesis is the contrast. The outcome claim is X (the asserted explanation, e.g. "rapamycin suppresses cancer mortality"), with `qualifiers: {contrast: a1}`; Y goes to `declared_alternatives` with `stated_as: rejected` and its own verbatim `source_span`. The effect being explained (e.g. "rapamycin extends mouse lifespan") is a `premise` claim. The outcome status follows the contrast rule (section 7).

## 7. Verified layer

```yaml
verification:
  claims:
    - id: c3
      status: supported               # supported | contested | refuted | unverified | unresolved
      evidence: [EvidenceRecord, ...]
      counterevidence: [EvidenceRecord, ...]
      refusals: [{type, record_id, quote, notes}]   # type: type_mismatch | direction_mismatch | species_mismatch | endpoint_mismatch | inherited_mismatch
      notes: "..."
    - id: an1                         # claim added by the verifier (analog, translation); ids an<N>, never in the declared layer
      claim: {subject: ..., relation: ..., object: ..., qualifiers: {...}}
      status: supported
      evidence: [EvidenceRecord, ...]
  evidence_profile:                   # computed, section 8
    gate: pass                        # pass | filtered
    gate_reason: "PMID:..."           # only when filtered: the refuting record (or the contrast rule)
    effect_level: mammals
    intervention_match: regimen_differs   # grade of the evidence that sets effect_level
    effect_contested: [human_markers]
    robustness: replicated
    multi_site_program: {tested: yes, outcome: positive}
    mechanism: partial
    next_step: "human_markers: trial with pre-registered primary outcome"
    conflicts: [{rung: human_markers, for: ["PMID:..."], against: ["PMID:..."], against_is_program: no}]
  alternatives:                       # section 8c; added by the pipeline after the verifier, not by the normalizer
    - {id: alt1, type: indirect_route.food_intake, source: checklist, status: open, discriminating_design: "pair-fed controls"}
    - {id: alt2, type: competitor, ref: H-0042, source: proximity, status: open}
    # ids: a<N> declared (normalizer), alt<N> pipeline-added, an<N> verifier-added analogs
    # source: checklist | proximity | debate | declared | expert
  prediction_table:                   # section 8c; rows = H and each alternative, columns = observables of the decisive experiment
    - {observable: "lifespan effect under pair feeding", H: persists, alt1: disappears}
  decision_criteria: {supports: "...", weakens: "...", inconclusive: "..."}   # read from the prediction table
  declared_vs_verified: [...]         # e.g. declared novelty contradicted by found prior work
```

`EvidenceRecord` (same as in [design notes, section 5b. Evidence record: what "every claim carries its sources" means](working-notes.md) and [data sources, section 13. Source anatomy: six epistemic types (2026-10-15)](data-sources.md)):

```yaml
source: PubMed | DrugAge | OpenGenes | ClinicalTrials.gov | GEO | ...
record_id: "PMID:..."
epistemic_type: A_text | B_curated | C_measurement      # D/E/F never set a status
study_type: primary_experiment | rct | open_label_pilot | observational | review | ...
lab_or_cohort: "..."                # research group, cohort or trial id; robustness counts distinct values
derived_from: "..."                 # record id if review / reanalysis of the same data; such records do not add robustness
species: ...
strain: ...                          # optional; e.g. UM-HET3, C57BL/6J, N2
sex: male | female | both | unknown   # of the animals or participants the finding refers to
dose: ...                            # optional, as reported
age_at_start: ...                    # optional, as reported
human_rungs: [human_markers, human_clinical]   # human records only, filled by the verifier from the record's endpoints (section 8)
location: "abstract, sentence 3"
quote: "verbatim fragment"
quote_role: finding | background | speculation
metric: ...
qualifiers_match: {species: yes|no|n/a, strain: yes|no|n/a, sex: yes|no|n/a, age_at_start: yes|no|n/a, dose: yes|no|n/a, comparator: yes|no|n/a,
                   intervention_match: exact|dose_differs|regimen_differs|related_compound|class}
marker_validation: validated_surrogate | exploratory | n/a   # human marker evidence only
flags: [retracted, preprint, conflict_of_interest, small_n, open_label, subgroup_only, short_lived_controls]
notes: "..."                       # optional, free text
linked_pmid: ...                     # B_curated only: the paper behind the curated row
fields: {...}                        # B_curated only: the row's own fields (e.g. DrugAge avg_lifespan_change_percent)
retrieved_at: 2026-10-15
```

Status rules:
- `supported`: ≥1 record with `quote_role: finding` (A or B with linked quote, or C executed test), qualifiers match, no matching counterevidence.
- `contested`: findings both for and against with matching qualifiers, or the only support is a subgroup / secondary outcome while the primary outcome is null.
- `refuted`: counterevidence findings with matching qualifiers and no support.
- `unverified`: no admissible evidence found (background and speculation do not count).
- `unresolved`: entities could not be mapped to identifiers, so the claim could not be checked.

Endpoint must match (agreed 2026-10-18): a finding supports or refutes a claim only if it measures the claim's endpoint (`pico.outcome.endpoint`: lifespan, healthspan, biomarker, disease, mechanism). A healthspan or marker finding does not support a lifespan claim; such records go to `refusals` with type `endpoint_mismatch` and stay visible to the judge. No separate field: this is verifier quality, enforced by the verifier prompt and checked by a fixture ([card examples, section Example 5. Endpoint mismatch: resveratrol and mouse lifespan](hypothesis-card-examples.md)).

Qualifier matching (agreed 2026-10-19):
- A qualifier that is `unknown` in the card gives `n/a` in `qualifiers_match`, never `no`: an unknown comparator, sex or age does not turn into a mismatch. `n/a` counts as matching.
- A qualifier the evidence does not report (e.g. an abstract without age at start) is left out of `qualifiers_match`; it neither blocks nor confirms the match.
- **`intervention_match` for curated records** (agreed 2026-10-20, rules over fields, no free-text comparison of regimens): card `route` differs from the record (DrugAge ppm in food → `diet`, in drinking water → `water`) → `regimen_differs`; card regimen intermittent or weekly while the record is continuous → `regimen_differs`. `dose_differs` is not set by code; the model sets it for PubMed records.
- **Strain** (agreed 2026-10-20): strain unspecified in the card → `n/a`, a finding in any strain of the species counts directly. Strain specified and different → the record does not support the claim directly; the verifier adds an analog claim `an<N>` (same intervention, same species, other strain), which counts for `effect_level` (section 8) but not for `known_result`. An inherited strain that differs → soft refusal `inherited_mismatch`, the analog is still added.
- A mismatch on an inherited qualifier (`inherited_from_pico`) is a soft refusal: the record goes to `refusals` with type `inherited_mismatch`, does not set the status (a mouse finding still does not support a claim inherited as human), and is not reported as a normalizer or species error.

Contrast rule (claims with `qualifiers.contrast`, section 6; agreed 2026-10-19). The verifier checks the rejected alternative Y like any claim; "same context" = same species, and same strain if both specify it. The outcome status, in order of precedence:

| X (asserted) | Y (rejected alternative) | Outcome |
|---|---|---|
| refuted | any | `refuted` |
| any | supported | `refuted` (even if X is supported) |
| any other | contested | `contested` |
| any other | refuted | X's status |
| supported | unverified / unresolved | `unverified`, flag `contrast_unchecked` (no support for free) |
| any other | unverified / unresolved | X's status |

Why `unverified` rather than `contested` for an unchecked Y: `contested` means findings both for and against, and it routes the hypothesis to debates on contested evidence (judge role A); an unchecked contrast has no conflicting findings. Evidence for X stays attached and visible. Record the inputs: `contrast: {alternative: a1, x_status: ..., y_status: ...}` on the outcome claim.

Real split on Y (agreed 2026-10-21, Example 3): when independent findings on Y disagree, Y is `contested` and the outcome is `contested` by the table. There is no extra rule for "X unverified, Y contested": the split is the true state of the literature, and debates on contested evidence exist for exactly this case. The verifier therefore searches Y in both directions (support and refutation) and does not stop at the first confirming record. The row "Y supported → outcome refuted" is covered by a synthetic unit test, since no real fixture exercises it now.

Comparator matters: evidence against untreated controls does not support a claim stated against monotherapy (synergy), and short-lived controls are a known source of spurious lifespan effects (flag `short_lived_controls`).

Flags lower trust but do not change status by themselves; they are visible to the judge.

## 7a. Expert layer (agreed 2026-10-19)

Third layer next to declared and verified ([design notes, section 2.5 Expert in the loop (agreed 2026-10-19)](working-notes.md)). It records expert decisions; it never edits the other two layers.

```yaml
expert:
  - id: e1
    by: "name or role"                # who
    at: 2026-10-19                    # when
    point: evidence_conflict          # profile | pairwise | evidence_conflict | objection | alternative | variant | portfolio
    target: c3                        # claim, objection, alternative, variant or hypothesis id; for pairwise: [H-A, H-B]
    decision: "..."                   # e.g. accept | reject | prefer H-A | take into work
    rationale: "..."
    source: "PMID:..."                # optional
```

Rules:
- A claim status changes only if the expert gives a `source`; the source goes through the verifier as any other evidence record. Without a source, the decision stays in this layer and is visible to judges as "expert opinion", not as a fact.
- `pairwise` decisions are copied into the preference profile as weight constraints ([aggregation spec, section 6a. Expert pairwise choices as weight constraints](aggregation-spec.md)).
- Hypotheses written by the expert are `RawHypothesis` with `origin: expert` and go through the same pipeline.
- `portfolio` and `pairwise` decisions are validation labels; autonomous-mode results are computed without this layer.

## 8. Evidence profile (computed; replaces the S0–S5 ladder, agreed 2026-10-18)

Goal: minimal arbitrariness, maximal use for our tasks (judge, path to humans, backtest, KG). Every field is a fact computed from verified claims; we never trade one axis against another here. How much each axis matters is a parameter of aggregation (ASPID/МРСП takes ordinal importance and randomizes weights), not of the classification.

**Gate (formerly S0, "not contradicted").** If the outcome claim or any `mechanism`/`premise` claim is `refuted`, the hypothesis is filtered out with the refuting record as the reason. `contested` does not filter.

**Three axes and one flag:**

| Axis | Values | Computed from |
|---|---|---|
| `effect_level` | none · cells · invertebrates · mammals · human_markers · human_clinical | highest rung where the outcome claim, or an `analog`/`translation` claim **with the same intervention** (same subject as `pico.intervention`; `intervention_match` exact, dose_differs or regimen_differs, shown in the profile), is `supported`. Related compounds and classes count only as analogs. A `contested` higher rung is reported next to it ("mammals; human_markers contested") |
| `robustness` | single · replicated | at the `effect_level` rung: one source / ≥2 independent sources (distinct `lab_or_cohort`, records with `derived_from` excluded) with matching qualifiers. A multi-site program with the effect at ≥2 sites counts as replicated |
| `mechanism` | supported · partial · unverified · refuted | statuses of `mechanism` and `premise` claims: all supported / some supported / none supported / any refuted (→ gate) |

**Flag `multi_site_program`** (yes / no, with outcome positive / negative): the intervention was tested at this rung in a standardized, pre-registered multi-site program that publishes negative results (ITP, CITP). Kept as a flag, not a robustness level: multi-site tests repeatability under one protocol, independent replication tests generalization across conditions, and we do not rank one over the other. These results are the cleanest backtest labels.

**Refinement fields** (data, not rules; visible to the judge and aggregation):
- `conflicts: [{rung, for: [record ids], against: [record ids], against_is_program: yes|no}]`. No rule says which side wins; e.g., a negative ITP result against one positive single-lab study is shown as such.
- **Human rungs by endpoint (agreed 2026-10-20):** `human_markers` = laboratory and instrumental measures without direct meaning for how a person feels or lives (blood biomarkers, epigenetic clocks, body composition such as lean or fat mass, arterial stiffness, blood pressure); `human_clinical` = what a person feels or what shapes their life (physical function such as gait speed, grip strength, 6-minute walk; frailty; pain; disease incidence; hospitalization; mortality). The verifier records this in `human_rungs` of each human evidence record (the `endpoint` field cannot tell lean mass from gait speed, both are healthspan); the claim status is computed separately per rung, so a record with both kinds of endpoints counts at each rung for its own endpoints (PEARL: contested on both).
- `human_markers` evidence carries `marker_validation`; the profile reports e.g. "human_markers (exploratory only)".
- Human rungs carry study design (agreed 2026-10-18): if every supporting record at the rung has `study_type: observational`, the profile reports e.g. "human_clinical (observational only)". Not a separate rung: ordering observational mortality data against RCT marker data would be the kind of weighting left to aggregation. Matters for aging because RCTs with lifespan or mortality endpoints are almost absent, so most human evidence is observational (e.g., metformin: PMID 25041462 vs PMID 36287641).
- `intervention_match` grade of the evidence that sets `effect_level`.

The only order we impose is the rung order of `effect_level` (proximity to humans). Analogs with a different subject (e.g., knockout of the drug's target gene) do not raise `effect_level`; they stay visible as claims in the judge packet.

**Derived: `next_step`** (practical "what to do next", shown outside the ranking; [design notes](working-notes.md) section 3):
- `robustness: single` at an animal rung → replicate at the same rung (multi-site if mammals);
- otherwise → the next rung up;
- a contested rung → resolve that rung (e.g., a trial with a pre-registered primary outcome).

`next_step` determines `decisive_experiment.system`. It is shown to the user as "what to do next", outside the ranking; the ranking uses `path_to_human` (section 8a).

**Validation (does it work?).** On the backtest, check that the axes discriminate: e.g., among hypotheses at "mammals · single" in year T, which later got a positive `multi_site_program` result (ITP) or human evidence; and that `path_to_human` classes are consistent with what was actually done later (e.g. registry entries). If an axis carries no signal, drop it.

## 8a. Scoring indicators for АСПИД (draft, 2026-10-19)

Decision ([design notes, section 2.2 Judge role and its link to АСПИД (agreed 2026-10-18)](working-notes.md)): criteria are scored by rules from the verified card wherever possible, not by an LLM judge. Reason: absolute LLM scores compress and drift; the card was built so that most criteria have a symbolic value. Each indicator is computed once; АСПИД aggregates them under random weights consistent with an ordinal importance order (a parameter set by experts; default stance: verified evidence matters most).

| Indicator | Computed from | Type | Values → [0, 1] | Direction |
|---|---|---|---|---|
| `effect_level` | section 8 | rule | none · cells · invertebrates · mammals · human_markers · human_clinical → 0…5, /5 | higher better |
| `robustness` | section 8 | rule | single 0 · replicated 1 | higher better |
| ~~`multi_site_positive`~~ | flag `multi_site_program` | — | since 2026-10-23 not a scored indicator: a positive multi-site program is one condition of `robustness = replicated`; the flag stays in the evidence profile (negative → counterevidence → usually gate) | — |
| `mechanism` | section 8 | rule | unverified 0 · partial 0.5 · supported 1 (refuted → gate) | higher better |
| `novelty` | `known_result`, `intervention_match`, KG lookup of (intervention, relation, outcome, species) | rule + KG | ordinal levels: `new_context` (same intervention and species, other strain, sex, dose or start age) < translation of a known finding to a new species < analog of a known intervention < new intervention–outcome link with a mechanistic anchor (`known_result` → ranked separately, not scored; levels mapped by SMAA-O). Since 2026-10-23 novelty is unknown (None, drawn uniformly) when there is no literature at all (flag `no_literature` in the evidence profile) or the link has no partly supported mechanism: absence of evidence is not novelty | higher better |
| `path_to_human` | number of preliminary steps before a human trial with marker/function endpoints: preclinical safety package if no human safety data (approved drug, clinical-stage compound, diet); mouse study if no supported mammalian effect (decided 2026-10-20, baseline) | rule | 0 steps cheap · 1 medium · 2 expensive (ordinal); gene target without a drug → unknown. Why classes differ by orders of magnitude: anchors in [design notes, section 3. Verification cannot be run "a little" → estimate cost and time instead](working-notes.md) | fewer better |
| `late_start` | `pico.age_at_start` vs species median lifespan (inputs below the table) | rule | fraction of median lifespan at start, capped at 1; a verbal age gives an interval, unknown = [0, 1] | higher better |
| `both_sexes` | `sex` of evidence records at `effect_level` | rule | both 1 · one 0.5 · none reported → unknown | higher better |
| `effect_size` | evidence `metric` at `effect_level` (e.g., % median lifespan) | rule (if extracted) | saturating normalization; cap open | higher better |
| `breadth` (optional) | hallmarks / age-related diseases linked in KG | rule + KG | count, saturating | higher better; disputed |
| `path_plausibility` (optional) | KG path intervention → target → pathway → hallmark for `unverified` links | rule + KG | path exists / length | higher better; weak |
| `informativeness` | `prediction_table` (section 8c; built at stage C together with debates, until then unknown and drawn uniformly) | rule | number (or share) of alternatives whose predicted pattern differs from H's on the decisive experiment's observables; saturating | higher better |

**`late_start` inputs** (agreed 2026-10-21; no models needed; the tables with values and sources: [data sources, section 19. late_start reference tables (collected 2026-10-21)](data-sources.md)).
- **Median lifespan table**: medians of control groups from sources with PMIDs, per species and, where it matters, strain and sex: UM-HET3 from ITP controls by sex, C57BL/6J, *C. elegans* N2, *D. melanogaster* reference strains, human life tables. AnAge is not used: its dataset gives maximum longevity only, no medians (checked 2026-10-21), and the maximum is noisy and depends on sample size. A species or strain missing from the table → `unknown`.
- **Exact ages** ("600 days", "20 months", "65 years") → number → fraction of the median.
- **Verbal ages** → an interval of the fraction via a small table: young adult / adult / middle-aged / old (aged, late life) / very old. Bounds are species-specific, taken with sources: a published life-phase classification for mice, accepted thresholds for humans (e.g. "older adults").
- In SMAA a verbal age is drawn uniformly within its interval ([aggregation spec](aggregation-spec.md) 2). Unknown is the interval [0, 1], so a verbal age narrows the spread without pretending to a point value.

Implementation of the aggregation (weight sampling, outputs, accuracy, tests): [aggregation spec](aggregation-spec.md).

Rules:
- **Backtest, as of T** (agreed 2026-10-20): `path_to_human` uses only information available at T: approved if ChEMBL first approval year ≤ year of T; clinical stage if ClinicalTrials.gov has a trial with the compound started before T; diet always counts as having human safety data. The mammalian-effect question already uses evidence dated ≤ T.
- **Unknown stays unknown:** an unknown value is drawn uniformly over its admissible range in each АСПИД draw, so data uncertainty and weight uncertainty add up in the score spread (no default values).
- The gate (section 8) removes refuted hypotheses before scoring.
- The [0, 1] mapping of ordinal levels: default SMAA-O random monotone mapping ([aggregation spec](aggregation-spec.md) section 2), equal steps as a sensitivity check.
- Determinism holds given the card; LLM errors upstream (normalizer, verifier, entity resolution) remain but are localizable per field.

## 8b. Proximity from the card (agreed in principle, 2026-10-19)

Co-Scientist's Proximity agent judges similarity with an LLM against the research goal (its pseudocode suggests text embeddings). The card allows a rule-based, typed proximity instead: similarity is computed over resolved entity IDs in PICO and over claims in the closed relation vocabulary, and the output is a **relation type**, not one number.

| Type | Rule | Use |
|---|---|---|
| `duplicate` | same intervention ID(s), species, outcome endpoint, relation and direction, same context qualifiers and same mechanism claims (strict, agreed 2026-10-21) | dedup |
| `variant` | same core, only qualifiers differ (dose, age at start, sex, strain, regimen, route, comparator, measure), or a mechanism is named in only one of the two; includes refinement siblings via `parent_id` | grouping |
| `competitor` | same intervention and outcome, different `mechanism` claims | debate pairing (judge role B: discriminating experiments, new alternatives) |
| `contradiction` | same claim triple, opposite direction | debate pairing; known-answer candidates |
| `analog` | different compounds sharing a ChEMBL mechanism target **and** an ATC level-4 class (agreed 2026-10-21); if one compound has no ATC code → `analog_weak`. E.g. sirolimus, everolimus, temsirolimus (FKBP1A + L04AH / L01EG). Shared narrow ChEBI class → `analog_weak` only if at least one compound has no ChEMBL mechanism target (see below) | similarity beyond names |
| `mechanism_neighbour` | different interventions acting on the same hallmark or pathway node | portfolio diversity; combination candidates |

**Duplicates** (agreed 2026-10-21). Strict on purpose: the same hypothesis with and without a named mechanism is a `variant`, so dedup never drops the version that names the mechanism. A duplicate of an earlier card is not verified again: it gets the outcome `duplicate` with `duplicate_of` and, in output formats that need a score per submitted row (ladder), the original's score. In our own ranking duplicates are collapsed into one entry before АСПИД, so copies do not take several top-k slots and shift P(top-k) of the others; the number of repeats is kept as metadata, not as merit.

**ChEBI classes** (agreed 2026-10-21). A class never gives a full `analog`. A shared narrow ChEBI class gives `analog_weak` only when at least one of the two compounds has no mechanism target in ChEMBL, so the class is the only information available; if both have targets, target + ATC decide and the class adds nothing. "Narrow" = the most specific common is_a ancestor, with a cap on the class size (number of member compounds) as a parameter set on the pool. Checked 2026-10-21: quercetin (CHEMBL50) and fisetin (CHEMBL31574) have no ChEMBL mechanisms and no ATC; their most specific common class is 7-hydroxyflavonol (CHEBI:52267) → `analog_weak`, while flavonoid (CHEBI:47916) is too broad. Sirolimus and tacrolimus share the narrow class macrolide lactam (CHEBI:145565), which is why the class alone is not enough: both have targets, and the ATC filter keeps them apart.

**Approximate duplicates** (embedding fallback for unresolved entities): not collapsed and ranked separately, because embeddings do not separate opposite claims; the pair gets the flag `duplicate_approx`, visible to the expert and judges.

**Why `analog` needs the ATC filter** (checked in the ChEMBL API 2026-10-21). A shared target alone is not enough: ChEMBL lists FKBP1A (CHEMBL1902) as the mechanism target for sirolimus, everolimus and temsirolimus, but also for tacrolimus and pimecrolimus. FKBP12 is only the binding partner: the rapalog complex inhibits mTOR, the tacrolimus complex inhibits calcineurin. ATC level 4 separates them: sirolimus L04AH01 / L01EG04 / S01XA23, everolimus L04AH02 / L01EG02, temsirolimus L01EG01 (mTOR kinase inhibitors) vs tacrolimus L04AD02 / D11AH01 (calcineurin inhibitors; agents for dermatitis) and pimecrolimus D11AH02. Some level-4 groups describe an indication rather than a mechanism (D11AH), so ATC only filters shared-target pairs, never creates an analog alone. Test: sirolimus–tacrolimus and sirolimus–pimecrolimus are not analogs.

Why not embeddings: "rapamycin extends mouse lifespan" and "rapamycin does not extend mouse lifespan" are near-identical as embeddings and opposite in meaning; the relation (`extends_lifespan_in` vs `no_lifespan_effect_in`) and `direction` separate them. The type also explains itself ("competitor: different mechanisms").

**One function, two uses.** The same card-similarity function applied to other pool hypotheses gives proximity (dedup, competitors, diversity); applied to `supported` edges of the KG it gives novelty (section 8a: known result, translation to a new species, analog, new link).

Limits: depends on entity resolution; cards with `unresolved` entities fall back to embedding similarity, marked as an approximation. `analog` needs target/class ontologies; mechanisms described in different words match only after mapping to pathway/target/hallmark nodes.

## 8c. Alternatives, prediction table and decision criteria (agreed 2026-10-19)

Source of the idea: DiscoveryRSI `2610.23839` represents a hypothesis as (claim, investigation plan, decision criteria, alternatives). Our decisive experiment already covers the plan; decision criteria and alternatives were missing.

**Who fills what.** The normalizer only parses the text: if the source lists alternatives or criteria, they go to `declared_alternatives` / `declared_decision_criteria` and are never scored (otherwise listing many alternatives would earn points: form over substance). Exception: an alternative with `stated_as: rejected` is part of the hypothesis's own content (contrast "mainly X, not Y", section 6). It is verified (section 7, contrast rule), searched for, and enters the prediction table as a row with `source: declared`; it still earns no points by itself. In the verified layer, **alternatives are added by a pipeline component after the verifier**, from three sources:
1. a checklist of failure modes (table below; seed: [design notes, section 6a. Where hypotheses come from and how they fail (2026-10-18)](working-notes.md)): added automatically by rules over card fields, no LLM, so two cards with the same fields get the same alternatives;
2. `competitor` hypotheses from card-based proximity (section 8b);
3. debates (judge role B), which add alternatives the checklist misses and propose discriminating designs for alternatives without a known one.

**Checklist of alternatives (agreed 2026-10-20).** Each row has an inclusion rule over existing card fields (hypothesis type, species, intervention type and route, endpoint, and fields of the evidence records). When the rule holds, the pipeline adds an entry to `alternatives` with `source: checklist`; the verifier then looks for a study with the discriminating control (found → `excluded_by_evidence` with a quote, not found → `open`).

| id | Alternative explanation | Included when | Discriminating design | Example |
|---|---|---|---|---|
| `food_intake` | effect via reduced food intake (hidden caloric restriction) | endpoint lifespan, animal species, intervention not a diet | pair feeding; food intake and body weight measured | — |
| `body_temperature` | effect via lower body temperature | same | core temperature monitoring; thermoneutral housing | −0.3–0.5 °C extended median lifespan by 12–20% (PMID 17082459) |
| `microbes` | effect via bacteria or microbiota | species worm; or mouse with `route: diet \| water \| oral` | worms: killed bacteria, other strains; mice: antibiotics or germ-free animals | metformin in worms acts via *E. coli*, effect depends on the strain (PMID 23540700) |
| `exposure_failed` | the compound did not reach the intended exposure | `route: diet \| water` | measured concentration in food or blood | ITP: dimethyl fumarate reached 35% of the target dose in food (PMID 38041783) |
| `genetic_background` | effect of the genetic background, not of the intervention | intervention type gene, or all supporting evidence from one inbred strain (`strain`) | backcrossed lines, proper transgenic controls, genetically heterogeneous mice, strain panel (CITP) | Sir2: longevity disappeared after outcrossing (PMID 21938067) |
| `disease_specific` | effect through one disease (e.g. cancer), not through aging | species mouse, endpoint lifespan | cause of death and pathology; censoring disease deaths | rapamycin, PMID 22587563 (Example 3) |
| `sex_specific` | effect in one sex only | supporting evidence covers one sex or does not report it (`sex`) | both sexes | 16α-hydroxyestriol: +15% males, −7% females (PMID 38753230) |
| `dose_regimen` | effect only at this dose or start age | all supporting evidence at one dose and one start age (`dose`, `age_at_start`) | several doses and start ages | astaxanthin, meclizine (PMID 38041783 → 41843349) |
| `off_target` | effect not through the named target | mechanistic hypothesis with an `inhibits`/`activates` claim | knockout or knockdown of the target: effect persists → wrong mechanism | — |
| `assay_artifact` | target engagement is an assay artifact | same, and target engagement shown only in vitro | an independent assay | resveratrol and SIRT1, fluorophore artifact (PMID 15684413) |
| `confounding` | confounders explain the association | observational hypothesis | discordant twins, Mendelian randomization, RCT | metformin: higher mortality in a Danish registry with discordant twins (PMID 36287641) |
| `reverse_causation` | the outcome causes the exposure | observational hypothesis | temporal order, Mendelian randomization | — |
| `age_proxy` | the marker only reflects chronological age | biomarker hypothesis | prediction beyond chronological age | — |
| `disease_proxy` | the marker reflects disease, not aging | biomarker hypothesis | exclude people with the disease; independent cohort | — |

**Checking checklist alternatives (agreed 2026-10-20, cost):** for every hypothesis, one verifier call over the abstracts already retrieved: is the discriminating control present for each included alternative (found → `excluded_by_evidence` with a quote; not found → `open`). A dedicated search per alternative only for strong hypotheses (P(top-k) ≥ 0.5), as part of the checks before debates. The prediction table and `informativeness` come at stage C together with debates.

Not in the checklist because existing rules already handle them: single lab (`robustness`), short-lived controls (flag), healthspan instead of lifespan (refusal `endpoint_mismatch`), subgroup only (status `contested`), other population (context matching). Dropped as too narrow: FUdR dependence in worm assays.

Each alternative has `status`: `excluded_by_evidence` (a study with the discriminating control exists) or `open`; a declared rejected alternative (`source: declared`) carries its claim status from the verifier instead.

**Prediction table.** Rows: H and each alternative; columns: observables of the decisive experiment; cells: the predicted pattern. Example (rapamycin, mechanistic): "lifespan effect after censoring cancer deaths" — H ("via cancer"): disappears; alternative ("via aging"): persists; "non-neoplastic age-related pathology" — H: unchanged; alternative: delayed.

**Decision criteria are read from the table:** supports H = the pattern H predicts; weakens H = an alternative's pattern; inconclusive = patterns coincide or the experiment is underpowered. Templates by hypothesis type give the structure; an LLM fills slots from the card (endpoint, species, comparator) and the normalizer parses the result back:

| Type | Template |
|---|---|
| interventional | effect on the primary endpoint in the stated direction, in the stated species, vs the comparator; plus a row per open alternative (e.g., "effect disappears under pair feeding → food-intake route") |
| mechanistic | prediction table H vs competitors |
| biomarker | the marker predicts the outcome beyond chronological age in an independent cohort, or adds nothing |
| observational | the association persists in a confounding-robust design (twins, Mendelian randomization), or vanishes after adjustment (e.g., metformin, PMID 36287641) |

Decision criteria are the status rules (section 7) applied in advance to a future experiment. Uses: (1) pre-registration for debates (no moving the goalposts); (2) output for the user (what would refute the hypothesis); (3) automatic labelling for backtests: a later study is classified as supports / weakens / inconclusive by these criteria ([design notes, section 2.4 Closing the evolution loop (draft, 2026-10-19)](working-notes.md), evaluation protocol).

**Informativeness = number of table rows the experiment separates** (alternatives whose predicted pattern differs from H's). Checklist alternatives and proximity competitors are just different sources of rows, so one indicator suffices (section 8a).

## 9. Normalizer contract

Input: `RawHypothesis.text`. Output: declared `HypothesisCard` only.
- Fill only what the text states; everything else `unknown`. Never fill a missing critical field (section 4a) from background knowledge: report it as missing; refinement creates a new hypothesis instead. Example: no comparator in the text → `comparator: unknown`, not "standard diet".
- **Inheritance from PICO** (agreed 2026-10-19, narrowed 2026-10-20): only **species and strain**; only into claims (and rejected declared alternatives) about the intervention itself (`subject` matches `pico.intervention`); a key is inherited only if the claim's span does not name it (an organism in the object, e.g. "in mice", counts as a named species); never into molecular relations (`inhibits`, `activates`, `increases_expression`, `decreases_expression`, `part_of`); when these conditions hold, inheritance is mandatory, so the result is deterministic; for relations whose object is an organism the inherited species also fills the object; list inherited keys in `inherited_from_pico` and keep the value clean (`species: human`, not "human (from pico)"). Sex, age at start and comparator are not inherited (they are usually stated in the outcome claim; inheriting them into mechanism claims would create false mismatches). No inheritance into general mechanism claims (e.g. "senescent cells drive physical decline"). An inherited value is not "stated in the text": a mismatch is a soft refusal (section 7).
- **Contrast "mainly X, not Y"**: outcome = X with `qualifiers.contrast`, Y → `declared_alternatives` with `stated_as: rejected` (section 6).
- No statuses, no evidence, no outside facts.
- Every claim has `source_span` copied verbatim from the text.
- Use only the closed vocabulary; if nothing fits, `other` with a short note (an outcome with `other` triggers one re-parse with a hint, section 5).
- Exactly one `outcome` claim.
- Max 8 claims.
- Alternatives and decision criteria only if the text states them (`declared_*`); the normalizer never generates them (section 8c).

Generator prompt block (when hypotheses are generated internally): write `claim_plain`, a short narrative and, if possible, PICO; do not write claims or statuses (the normalizer does).

## 10. Programmatic validation (minimum)

- Enums valid; exactly one `outcome` claim; edges reference existing claims; no cycles through `requires`.
- Admission (section 4a): critical fields per type present → `accepted`, else `needs_refinement` / `not_a_hypothesis`; `parent_id` set for every refined variant; `known_result` check run on refined variants.
- No hypothesis disappears silently: `needs_refinement` → "awaiting refinement" list with `missing_critical`; outcome still `other` after the re-parse → flag `unmapped_relation`, "unparsed" list (section 5).
- `source_span` is a substring of the raw text (after whitespace normalization); also for `declared_alternatives`.
- `inherited_from_pico` ⊆ {species, strain}; each listed key is present in `qualifiers` with the PICO value; the `subject` matches `pico.intervention` (claims and declared alternatives).
- `qualifiers.contrast` references an existing `declared_alternatives` id with `stated_as: rejected`; such an alternative exists only together with a contrast claim.
- Interventional type ⇒ `pico.intervention` (≥1 item) and `pico.outcome.endpoint` not `unknown`.
- Verified layer: any status other than `unverified`/`unresolved` has ≥1 evidence record (for a contrast outcome: on the claim or on the referenced alternative); every quote is a verbatim substring of the fetched source text.

## 11. Judge packet (view)

Contains: `claim_plain`, PICO, claims with verified statuses and ≤1 short quote each, evidence profile (gate, three axes, next step), decisive experiment, `path_to_human` class and next step, risks, flags. Declared novelty is shown as "declared by source" next to found prior work. Generator identity, original wording style and self-assessed scores are hidden.

## 12. Open items

- Criteria for aggregation: draft indicator set in section 8a; importance orders = preference profiles (content open, [design notes](working-notes.md) item B5); saturation caps open.
- ~~Whether `observational` hypotheses need extra fields (cohort, design) beyond PICO.~~ Closed 2026-10-20: no. Design and cohort are properties of the studies (`study_type` in evidence records, "observational only" in the profile), the decisive experiment comes from the decision-criteria template (8c), confounding and reverse causation from the checklist.
- Identifier resolution for complexes (proposed 2026-10-20, for the KG): Complex Portal id for the species if it exists (mTORC1: mouse CPX-4473; no human entry found), else the GO cellular-component term (mTORC1: GO:0031931 "TORC1 complex", species-independent), optionally the member UniProt ids; matching across species via the GO term.
- Effect-size threshold in decision criteria: the hypothesis's declared size if given; otherwise "any significant effect" with a note. Taking a threshold from a reference class (e.g., typical +10–20% median lifespan in ITP) is an assumption to decide.
- `path_to_human` (section 8a) is a three-level baseline; finer cost and time estimates (dollar classes, durations by endpoint, ClinicalTrials.gov duration table) only if there is demand (Working_Notes section 3).
- Checklist of alternatives: written 2026-10-20 (section 8c); extend when new failure modes appear.
- ~~`late_start` tables (section 8a): values to be filled from sources.~~ Done 2026-10-21 ([data sources](data-sources.md) 19): mouse UM-HET3 and C57BL/6J by sex, worm N2 (20 °C), fly Dahomey females (25 °C), human (WHO life tables); verbal ages from JAX life phases and MeSH age groups. Rat and more fly strains on demand.
- Normalizer prompt v4: the section 9 contract is implemented but not yet run on a real model. Check on the raw texts of Examples 1–5 against the hand-written declared layers: verbatim spans, closed vocabulary, exactly one outcome, ≤ 8 claims, inheritance.

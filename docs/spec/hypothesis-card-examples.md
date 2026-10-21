# Hypothesis card: worked examples (v1)

> Four cards built by hand following [card spec](hypothesis-card-spec.md): three on the mTOR / senolytics slice (Examples 1–3; Example 3 is also the contrast fixture), an admission and refinement example (Example 4, spec section 4a) and an endpoint-mismatch fixture (Example 5, H-0006, added 2026-10-18). All four cards pass admission: each names species or population, intervention and outcome. Raw hypothesis texts are written for the example (they stand in for externally generated hypotheses). **All quotes are verbatim from PubMed abstracts fetched 2026-10-15 (Example 5: 2026-10-18; Example 3 re-checked 2026-10-19, PMID 23863708 added 2026-10-21)**; only abstracts were read, not full texts. Statuses follow the rules in spec section 7. These are also intended as test fixtures.

---

## Example 1. Interventional: low-dose rapamycin and human healthspan

**Raw text (R-0001):** "Weekly low-dose intermittent rapamycin, by inhibiting mTORC1, slows multiple aspects of aging and can improve healthspan in healthy older adults, as it does in mice where it extends lifespan even when started late in life."

### Declared layer (normalizer output)

```yaml
id: H-0001
raw_id: R-0001
hypothesis_type: interventional
claim_plain: Weekly low-dose rapamycin improves healthspan in healthy older adults.
pico:
  population: {taxon: "NCBITaxon:9606", label: human, sex: unknown, age_at_start: "older adults, healthy"}
  intervention:
    - {type: compound, label: rapamycin, id: "CHEBI:9168", regimen: "weekly, low-dose, intermittent"}
  comparator: unknown
  outcome: {endpoint: healthspan, metric: unknown}
  time: unknown
claims:
  - id: c1
    subject: {label: rapamycin}
    relation: inhibits
    object: {label: mTORC1}
    role: premise
    source_span: "by inhibiting mTORC1"
  - id: c2
    subject: {label: rapamycin}
    relation: slows_aging_in
    object: {label: human, id: "NCBITaxon:9606"}
    qualifiers: {species: human, measure: "multiple aspects of aging"}
    inherited_from_pico: [species]      # subject = the intervention → species inherited (spec 9, mandatory)
    role: mechanism
    source_span: "slows multiple aspects of aging"
  - id: c3
    subject: {label: rapamycin}
    relation: extends_lifespan_in
    object: {label: mouse, id: "NCBITaxon:10090"}
    qualifiers: {age_at_start: late_life}
    role: analog
    source_span: "in mice where it extends lifespan even when started late in life"
  - id: c4
    subject: {label: rapamycin}
    relation: improves_healthspan_in
    object: {label: human, id: "NCBITaxon:9606"}
    qualifiers: {age_at_start: older_adults}   # dose is not in this span; it lives in pico.intervention.regimen
    role: outcome
    source_span: "can improve healthspan in healthy older adults"
edges:
  - {from: c2, to: c1, type: requires}
  - {from: c2, to: c4, type: supports_if_true}
  - {from: c3, to: c4, type: analog_of}
declared_novelty: unknown
decisive_experiment: {system: human, endpoint: "healthspan composite / physical function", duration_class: years}
risks: []
```

### Verified layer

```yaml
verification:
  claims:
    - id: c1
      status: unverified
      notes: >-
        The only fetched mention is background: PMID 19587680 abstract, "rapamycin, an inhibitor of
        the mTOR pathway" (quote_role: background). A primary pharmacology source is still needed.
    - id: c2
      status: unverified                       # changed 2026-10-19: species inherited as human, the finding is in mice
      refusals:
        - type: inherited_mismatch
          record_id: "PMID:22587563"          # Wilkinson et al. 2012, Aging Cell
          quote: "many forms of age-dependent change, including alterations in heart, liver, adrenal glands, endometrium, and tendon, as well as age-dependent decline in spontaneous activity, occur more slowly in rapamycin-treated mice"
          notes: "mouse finding vs species inherited from PICO (human): soft refusal, visible, does not set the status"
      notes: >-
        Same abstract reports harms: "mice treated with rapamycin starting at 9 months of age have
        significantly higher incidence of testicular degeneration and cataracts" (goes to risks).
    - id: c3
      status: supported
      evidence:
        - source: PubMed
          record_id: "PMID:19587680"          # Harrison et al. 2009, Nature
          epistemic_type: A_text
          study_type: primary_experiment
          species: mouse
          quote: "On the basis of age at 90% mortality, rapamycin led to an increase of 14% for females and 9% for males."
          quote_role: finding
          metric: age at 90% mortality
          qualifiers_match: {species: yes, age_at_start: yes}   # fed from 600 days of age
        - source: DrugAge
          record_id: "rapamycin / UM-HET3 / 20 months"
          epistemic_type: B_curated
          linked_pmid: 19587680
          metric: average lifespan
          fields: {avg_lifespan_change_percent: "13 (F), 9 (M)", significance: S, ITP: Yes}
      notes: 'Same abstract: "The effect was seen at three independent test sites in genetically heterogeneous mice" → counts as replicated, multi_site_program: yes.'
    - id: c4
      status: contested
      evidence:
        - source: PubMed
          record_id: "PMID:40188830"          # Moel et al. 2025, PEARL trial
          epistemic_type: A_text
          study_type: rct
          species: human
          quote: "Lean tissue mass (ηp2 = 0.202, p = 0.013) and self-reported pain (ηp2 = 0.168, p = 0.015) improved significantly for women using 10 mg rapamycin."
          quote_role: finding
          human_rungs: [human_markers, human_clinical]   # lean mass = marker, pain = clinical
          flags: [subgroup_only, conflict_of_interest]
      counterevidence:
        - source: PubMed
          record_id: "PMID:40188830"
          epistemic_type: A_text
          study_type: rct
          quote: "Visceral adiposity did not change significantly (ηp2 = 0.001, p = 0.942)"
          quote_role: finding
          human_rungs: [human_markers]
          notes: primary outcome of the trial
      notes: >-
        48-week double-blind placebo-controlled trial (NCT04488601) of 5 or 10 mg weekly. Primary
        outcome null; positives are secondary/subgroup. Authors are employees and shareholders of the
        sponsor. Related but not admissible for c4 (different compound): PMID 25540326, RAD001
        "enhanced the response to the influenza vaccine by about 20%" in elderly volunteers.
  evidence_profile:
    gate: pass
    effect_level: mammals              # c3, same intervention in mice
    intervention_match: regimen_differs   # ITP: rapamycin in diet, continuous; card: weekly intermittent
    effect_contested: [human_markers, human_clinical]  # c4, PEARL: lean mass (marker) and pain (clinical), women 10 mg subgroup only; primary outcome null
    robustness: replicated             # effect at three ITP sites
    multi_site_program: {tested: yes, outcome: positive}   # ITP
    mechanism: unverified              # c1 and c2 unverified (c2: only mouse evidence)
    next_step: "human: trial with pre-registered primary outcome (function)"
    conflicts:                         # subgroup positive, primary null (visceral adiposity, a marker)
      - {rung: human_markers, for: ["PMID:40188830"], against: ["PMID:40188830"], against_is_program: no}
      - {rung: human_clinical, for: ["PMID:40188830"], against: ["PMID:40188830"], against_is_program: no}
  declared_vs_verified:
    - "c1 is stated as fact in the hypothesis but has no admissible evidence yet."
    - "c2 is supported in mice (PMID 22587563) but stated for humans."
```

**What the example shows:** a plausible-sounding hypothesis with a solid mouse result (mammals, replicated in ITP) but a contested human outcome; a premise that is "common knowledge" yet unverified until a finding is attached; a mechanism shown in mice that does not count for a human claim (inherited species, soft refusal); harms surfaced from the same abstracts.

---

## Example 2. Interventional: senolytics and physical function

**Raw text (R-0002):** "Intermittent dasatinib plus quercetin improves physical function in older adults because it clears senescent cells and lowers their inflammatory secretions (SASP), which drive physical decline."

### Declared layer

```yaml
id: H-0002
raw_id: R-0002
hypothesis_type: interventional
claim_plain: Intermittent dasatinib plus quercetin improves physical function in older adults.
pico:
  population: {taxon: "NCBITaxon:9606", label: human, age_at_start: "older adults"}
  intervention:                         # combination → two items
    - {type: compound, label: dasatinib, regimen: intermittent}
    - {type: compound, label: quercetin, regimen: intermittent}
  comparator: unknown
  outcome: {endpoint: healthspan, metric: "physical function"}
  time: unknown
claims:
  - id: c1
    subject: {label: "dasatinib + quercetin"}
    relation: suppresses
    object: {label: "senescent cell burden", hallmark: cellular_senescence}
    qualifiers: {species: human, direction: decrease}
    inherited_from_pico: [species]      # "it" = D+Q in older adults; species not stated in the span
    role: mechanism
    source_span: "it clears senescent cells"
  - id: c2
    subject: {label: "dasatinib + quercetin"}
    relation: suppresses
    object: {label: "SASP"}
    qualifiers: {species: human}
    inherited_from_pico: [species]
    role: mechanism
    source_span: "lowers their inflammatory secretions (SASP)"
  - id: c3
    subject: {label: "senescent cells / SASP"}
    relation: promotes
    object: {label: "physical decline"}
    qualifiers: {species: unknown}      # general mechanism claim: subject is not the intervention → no inheritance
    role: mechanism
    source_span: "which drive physical decline"
  - id: c4
    subject: {label: "dasatinib + quercetin"}
    relation: improves_healthspan_in
    object: {label: human, id: "NCBITaxon:9606"}
    qualifiers: {age_at_start: older_adults, measure: "physical function"}
    role: outcome
    source_span: "improves physical function in older adults"
edges:
  - {from: c4, to: c1, type: requires}
  - {from: c1, to: c2, type: supports_if_true}
  - {from: c3, to: c4, type: supports_if_true}
declared_novelty: unknown
decisive_experiment: {system: human, endpoint: "physical function (gait speed, 6-min walk)", duration_class: months}
risks: []
```

### Verified layer

```yaml
verification:
  claims:
    - id: c1
      status: unverified
      notes: >-
        Only ex vivo evidence: PMID 29988130 (Xu et al. 2018, Nat Med), "decreased the number of
        naturally occurring senescent cells and their secretion of frailty-related proinflammatory
        cytokines in explants of human adipose tissue". The declared claim is about older adults in vivo,
        so the context does not match; the record is kept as related evidence.
    - id: c2
      status: unverified
      notes: >-
        Measured in humans but inconclusive: PMID 30616998 (Justice et al. 2019), "were inconclusive,
        but correlations were observed between change in function and change in SASP-related
        matrix-remodeling proteins" (open-label pilot, n = 14, IPF patients).
    - id: c3
      status: supported
      evidence:
        - source: PubMed
          record_id: "PMID:29988130"
          epistemic_type: A_text
          study_type: primary_experiment
          species: mouse
          quote: "transplanting relatively small numbers of senescent cells into young mice is sufficient to cause persistent physical dysfunction"
          quote_role: finding
          qualifiers_match: {species: n/a}     # declared species unknown → n/a (counts as matching)
          flags: [conflict_of_interest]       # patents on senolytic drugs held by Mayo Clinic
    - id: c4
      status: unverified
      notes: >-
        Related human evidence in a different population: PMID 30616998, "Physical function evaluated as
        6-min walk distance, 4-m gait speed, and chair-stands time was significantly and
        clinically-meaningfully improved (p < .05)" — open-label, n = 14, idiopathic pulmonary fibrosis,
        not healthy older adults → population does not match.
    - id: an1                                  # analog added by the verifier, not declared (renamed from a1 to avoid a clash with alternative ids)
      claim: {subject: "dasatinib + quercetin", relation: improves_healthspan_in, object: mouse, qualifiers: {age_at_start: old}}
      status: supported
      evidence:
        - source: PubMed
          record_id: "PMID:29988130"
          epistemic_type: A_text
          species: mouse
          quote: "intermittent oral administration of senolytics to both senescent cell-transplanted young mice and naturally aged mice alleviated physical dysfunction and increased post-treatment survival by 36% while reducing mortality hazard to 65%."
          quote_role: finding
          flags: [conflict_of_interest]
  evidence_profile:
    gate: pass
    effect_level: mammals              # an1, same intervention in aged mice
    intervention_match: exact          # intermittent D+Q in both
    robustness: single                 # no independent replication found
    multi_site_program: {tested: no}
    mechanism: partial                 # c3 supported, c1 and c2 unverified
    next_step: "mammals: independent (ideally multi-site) replication"
    # human evidence exists only in a disease population (IPF) → does not count
  declared_vs_verified:
    - "c1 and c2 are stated as established in humans; admissible evidence is ex vivo or inconclusive."
```

**What the example shows:** strict context matching (ex vivo ≠ in vivo; IPF patients ≠ healthy older adults) keeps attractive but mismatched evidence from inflating the status; verifier-added analogs live in the verified layer only; conflict-of-interest flags are visible.

---

## Example 3. Mechanistic: why rapamycin extends lifespan

Contrast fixture "mainly X, not Y" (restructured 2026-10-19, spec sections 6 and 7): the outcome is the asserted explanation X, the rejected explanation Y is a declared alternative that the verifier checks.

**Raw text (R-0003):** "Rapamycin extends mouse lifespan mainly by postponing death from cancer, not by slowing aging itself."

### Declared layer

```yaml
id: H-0003
raw_id: R-0003
hypothesis_type: mechanistic
claim_plain: Rapamycin's lifespan effect in mice comes from delayed cancer death rather than slower aging.
pico:
  population: {taxon: "NCBITaxon:10090", label: mouse}
  intervention:
    - {type: compound, label: rapamycin, id: "CHEBI:9168"}
  comparator: unknown
  outcome: {endpoint: mechanism, metric: "cause of lifespan extension"}
  time: unknown
claims:
  - id: c1
    subject: {label: rapamycin}
    relation: extends_lifespan_in
    object: {label: mouse, id: "NCBITaxon:10090"}
    role: premise                       # the effect being explained
    source_span: "Rapamycin extends mouse lifespan"
  - id: c2
    subject: {label: rapamycin}
    relation: suppresses
    object: {label: "cancer mortality"}
    qualifiers: {species: mouse, contrast: a1}
    inherited_from_pico: [species]
    role: outcome                       # X: the asserted explanation
    source_span: "mainly by postponing death from cancer"
edges:
  - {from: c2, to: c1, type: supports_if_true}
declared_alternatives:
  - id: a1                              # Y: the explanation the author rejects
    subject: {label: rapamycin}
    relation: slows_aging_in
    object: {label: mouse, id: "NCBITaxon:10090"}
    qualifiers: {species: mouse, measure: "age-related changes, non-neoplastic"}
    inherited_from_pico: [species]
    source_span: "not by slowing aging itself"
    stated_as: rejected
declared_novelty: unknown
decisive_experiment: {system: mouse, endpoint: "cause-of-death and non-neoplastic aging pathology", duration_class: years}
risks: []
```

### Verified layer

```yaml
verification:
  claims:
    - id: c1
      status: supported
      evidence:
        - source: PubMed
          record_id: "PMID:19587680"
          epistemic_type: A_text
          species: mouse
          quote: "Here we report that rapamycin, an inhibitor of the mTOR pathway, extends median and maximal lifespan of both male and female mice when fed beginning at 600 days of age."
          quote_role: finding
    - id: c2
      status: contested                 # contrast rule: Y contested → outcome contested (spec 7)
      contrast: {alternative: a1, x_status: unverified, y_status: contested}
      notes: >-
        X on its own is unverified: the closest sentence is speculation, PMID 19587680, "Rapamycin may extend
        lifespan by postponing death from cancer, by retarding mechanisms of ageing, or both" (quote_role:
        speculation); the same abstract reports "Disease patterns of rapamycin-treated mice did not differ
        from those of control mice", which does not support a cancer-specific mechanism.
    - id: a1
      status: contested                 # independent mouse studies disagree
      evidence:
        - source: PubMed
          record_id: "PMID:22587563"      # Wilkinson et al. 2012, Aging Cell, "Rapamycin slows aging in mice"
          epistemic_type: A_text
          species: mouse
          quote: "suggesting strongly that rapamycin retards multiple aspects of aging in mice, in addition to any beneficial effects it may have on neoplastic disease"
          quote_role: finding
          qualifiers_match: {species: yes, intervention_match: exact}
      counterevidence:
        - source: PubMed
          record_id: "PMID:23863708"      # Neff et al. 2013, J Clin Invest, "Rapamycin extends murine lifespan but has limited effects on aging"
          epistemic_type: A_text
          species: mouse
          strain: C57BL/6J
          sex: male
          quote: "Therefore, our data largely dissociate rapamycin's longevity effects from effects on aging itself."
          quote_role: finding
          qualifiers_match: {species: yes, strain: n/a, sex: n/a, intervention_match: exact}   # strain and sex unspecified in the card → n/a
          notes: >-
            Lifespan was extended, but few aging phenotypes improved; several traits rescued in old mice
            changed similarly in young ones, i.e. aging-independent drug effects.
  evidence_profile:
    gate: pass                          # outcome contested, not refuted → no filtering
  alternatives:
    - {id: a1, source: declared, status: contested}   # declared rejected alternative: carries its claim status
  prediction_table:                    # spec 8c
    - {observable: "lifespan effect after censoring cancer deaths", H: disappears, a1: persists}
    - {observable: "non-neoplastic age-related pathology", H: unchanged, a1: delayed}
  declared_vs_verified:
    - "The hypothesis builds on a speculative sentence of the original paper; X itself has no direct support. Later work on the rejected explanation Y is split: PMID 22587563 supports it, PMID 23863708 largely rejects it."
```

Search: the verifier queries the alternative in both directions (e.g. "rapamycin age-related changes mice", "rapamycin non-neoplastic lesions mice", "rapamycin aging phenotypes young and old mice"); a search only for X finds neither PMID 22587563 nor PMID 23863708, and a search that stops at the first confirming record misses the split.

**What the example shows:** the contrast rule on a real split (Y contested → outcome contested, the hypothesis is not filtered and becomes a candidate for debates on contested evidence); the speculation / finding distinction within one abstract; why such hypotheses are informative (they discriminate between competing explanations named by the original authors). Changed 2026-10-21: the first version had only PMID 22587563 (a1 supported → outcome refuted, filtered); the live verifier also found PMID 23863708, and the fixture now matches the real literature. The row "Y supported → refuted" is tested on a synthetic case (spec 7).

---

## Example 4. Admission and refinement: a vague hypothesis

Shows spec section 4a: `needs_refinement`, refined variants with `parent_id`, the known-result check, and a `not_a_hypothesis` case.

**Raw text (R-0004):** "Senolytics slow aging."

### Admission

```yaml
raw_id: R-0004
hypothesis_type: interventional
admission: needs_refinement
missing_critical: [pico.population, pico.outcome.endpoint]
notes: >-
  Intervention is a drug class, not a compound; no species or population; "slow aging" has no
  measurable endpoint. No decisive experiment can be defined (worm, mouse and human tests differ by
  orders of magnitude in cost and time), so the text is not ranked as is.
```

### Refined variants (new hypotheses, `origin: internal`)

```yaml
- id: R-0004a
  parent_id: R-0004
  origin: internal
  text: "Intermittent dasatinib plus quercetin started in old mice increases their remaining survival."
  admission: accepted
  context_specificity: 3          # species, age at start, regimen
  known_result: true
  notes: >-
    The outcome claim matches an existing supported finding in the same context (same intervention,
    species, age at start): PMID 29988130, "intermittent oral administration of senolytics to both
    senescent cell-transplanted young mice and naturally aged mice alleviated physical dysfunction and
    increased post-treatment survival by 36% while reducing mortality hazard to 65%." Zero novelty;
    ranked separately, not as a new hypothesis.

- id: R-0004b
  parent_id: R-0004
  origin: internal
  text: "Intermittent dasatinib plus quercetin improves physical function in older adults because it clears senescent cells and lowers their inflammatory secretions (SASP), which drive physical decline."
  admission: accepted
  context_specificity: 3          # species (human), age at start (older adults), regimen
  known_result: false
  notes: >-
    Same text as R-0002 (Example 2); its card and verified layer are there. Admissible human evidence
    in this population was not found (only an IPF pilot), so this variant is new and testable; its
    next step is evidence in healthy older adults.
```

Entries combine `RawHypothesis` fields with the `Admission` result for readability. The parent R-0004 keeps its declared layer unchanged; each variant gets its own card. The two variants together show why refinement matters: one concretization is already known (no value as a hypothesis), the other is open and carries a defined decisive experiment.

### Not a hypothesis

**Raw text (R-0005):** "Senescent cells are bad for health."

```yaml
raw_id: R-0005
admission: not_a_hypothesis
reason: >-
  No intervention and no measurable outcome; as stated it cannot be refuted by one experiment.
  Stored as a direction ("senescent cell burden as a target"), not ranked. It can seed refinement
  into testable variants such as R-0004a or R-0004b.
```

---

## Example 5. Endpoint mismatch: resveratrol and mouse lifespan

Fixture for the endpoint rule in spec section 7 (added 2026-10-18; quotes verbatim from PubMed abstracts fetched 2026-10-18). The trap: the same abstract reports a broad healthspan improvement and no lifespan effect. A verifier that matches only species, intervention and age would mark the lifespan claim `supported`.

**Raw text (R-0006):** "Resveratrol started in middle age extends the lifespan of mice."

### Declared layer

```yaml
id: H-0006
raw_id: R-0006
hypothesis_type: interventional
claim_plain: Resveratrol given from middle age makes mice live longer.
pico:
  population: {taxon: "NCBITaxon:10090", label: mouse, age_at_start: "middle age"}
  intervention:
    - {type: compound, label: resveratrol, id: "CHEBI:27881"}
  comparator: unknown                   # not in the text (was "standard diet" before 2026-10-19: background knowledge, removed)
  outcome: {endpoint: lifespan, metric: unknown}
  time: unknown
claims:
  - id: c1
    subject: {label: resveratrol, id: "CHEBI:27881"}
    relation: extends_lifespan_in
    object: {label: mouse, id: "NCBITaxon:10090"}
    qualifiers: {age_at_start: "middle age"}
    role: outcome
    source_span: "Resveratrol started in middle age extends the lifespan of mice"
edges: []
declared_novelty: unknown
decisive_experiment: {system: mouse, endpoint: lifespan, duration_class: years}
risks: []
```

### Verified layer

```yaml
verification:
  claims:
    - id: c1
      status: refuted
      counterevidence:
        - source: PubMed
          record_id: "PMID:18599363"
          epistemic_type: A_text
          species: mouse
          quote: "mice fed a standard diet did not live longer when treated with resveratrol beginning at 12 months of age"
          quote_role: finding
          qualifiers_match: {species: yes, age_at_start: yes, comparator: n/a, intervention_match: exact}   # comparator unknown in the card → n/a
        - source: PubMed
          record_id: "PMID:20974732"
          epistemic_type: A_text
          species: mouse
          study_type: primary_experiment     # ITP: multi-site, three test sites
          quote: "Resveratrol (at 300 and 1200 ppm food) and simvastatin (12 and 120 ppm) did not have significant effects on survival in male or female mice."
          quote_role: finding
          qualifiers_match: {species: yes, comparator: n/a, intervention_match: exact}
      refusals:
        - type: endpoint_mismatch
          record_id: "PMID:18599363"
          quote: "resveratrol-fed elderly mice show a marked reduction in signs of aging"
          notes: "healthspan finding; does not support a lifespan claim"
  evidence_profile:
    gate: filtered
    gate_reason: "PMID:20974732"       # outcome claim c1 refuted (ITP)
    multi_site_program: {tested: yes, outcome: negative}
```

**What the example shows:** the healthspan sentence is a `finding` with matching species, intervention and age, and still must not count as support. Expected verifier output: no record of PMID 18599363 under `evidence`; the healthspan sentence appears only under `refusals`. The ITP abstract does not state the age at start for resveratrol, so `age_at_start` is left out of its `qualifiers_match` rather than guessed.

---

## Implementation notes

- Example 4 is the admission fixture: R-0004 → `needs_refinement` with the listed missing fields; R-0004a → `known_result`; R-0005 → `not_a_hypothesis`.
- These four cards (Examples 1, 2, 3, 5) can be used as fixtures: the declared layer is the expected normalizer output for the raw texts; the verified layer is the expected verifier output given the cited PMIDs.
- Quote check: every `quote` must be a verbatim substring of the abstract returned by `efetch` for that PMID (watch PubMed's own typos, e.g. "circulat.ing" in PMID 30616998, which is why that sentence is quoted from a different fragment).
- Updated 2026-10-19 (agreed): Example 5 comparator → `unknown` and `qualifiers_match.comparator: n/a`; Example 2 c1, c2 carry `inherited_from_pico: [species]`, c3 does not; Example 2 analog renamed `an1`; Example 3 restructured as the contrast fixture: c2 (X) is the outcome with `contrast: a1`, a1 (Y, `stated_as: rejected`) is checked and `supported` by PMID 22587563, so c2 → `refuted` by the contrast rule (superseded 2026-10-21: a1 is `contested`, see below). Expected search: queries for a1 find PMID 22587563 and PMID 23863708; if they do not, record it as a known weakness.
- Consistency pass 2026-10-19 (spec updated alongside): PICO `age` → `age_at_start`; inheritance from PICO is mandatory when the subject is the intervention, so **Example 1 c2 changed**: relation `slows_aging_in`, species inherited as human, the mouse finding (PMID 22587563) moves to `refusals` (`inherited_mismatch`), c2 → `unverified`, profile `mechanism: unverified`; c4 lost `dose` (not in its span); Example 2 c3 `qualifiers_match.species: n/a`; Example 3 a1 object = organism with `qualifiers.measure`, plus `alternatives` row and prediction table; `gate_reason` and `intervention_match` added to profiles; R-0004b `context_specificity` 2 → 3.
- 2026-10-20 (decisions): inheritance only of species and strain, only if the span does not name it, never into molecular relations (spec 9) — consistent with all fixtures as they stand; `human_rungs` on human evidence records (Example 1 PEARL records updated); `intervention_match` rules for curated records (spec 7); `path_to_human` as of T in backtests (spec 8a); checklist alternatives checked with one call per hypothesis, prediction table and informativeness at stage C — for Example 3 test the `alternatives` row now, the prediction table at stage C.
- 2026-10-20: strain rule (spec 4a, 7, 8a): other strain of the same species → analog `an<N>` (counts for `effect_level`, not for `known_result`); novelty level `new_context`. No fixture changes (no card specifies a strain).
- 2026-10-20: human rungs by endpoint (spec 8): Example 1 `effect_contested: [human_markers, human_clinical]` (lean mass = marker, pain = clinical), conflicts on both rungs.
- 2026-10-21 (decisions): **Example 3 changed**: PMID 23863708 (Neff 2013) added as counterevidence to a1 → a1 `contested`, c2 `contested` (contrast rule), `gate: pass`, no `gate_reason`; the row "Y supported → refuted" moves to a synthetic unit test. Outcome with `other` → one re-parse, then flag `unmapped_relation` and an "unparsed" list (spec 5). `needs_refinement` → "awaiting refinement" list, no variant generation yet (spec 4a); Example 4's refined variants stay as hand-written fixtures for later. `late_start` inputs (spec 8a): median table from control groups, verbal ages as intervals.
- 2026-10-21 (proximity, decisions): strict `duplicate` accepted; duplicates are not re-verified, get the original's score only in per-row output formats and are collapsed into one entry before АСПИД; `analog` = shared ChEMBL mechanism target + shared ATC level-4 class, else `analog_weak`; negative test: sirolimus vs tacrolimus / pimecrolimus (spec 8b).
- 2026-10-21 (proximity, second round): shared narrow ChEBI class → `analog_weak` only if one compound has no ChEMBL mechanism target (quercetin–fisetin yes, sirolimus–tacrolimus no); approximate duplicates not collapsed, flag `duplicate_approx`; `late_start`: `both` row when sex is unknown, worm/fly rows apply when conditions are unstated (spec 8b, Data_Sources 19).
- Example 5 is the endpoint fixture: H-0006 c1 → `refuted`; the healthspan sentence of PMID 18599363 must land in `refusals` (`endpoint_mismatch`), never in `evidence`.
- Context matching is the hardest part: species, in vivo vs ex vivo, population (healthy vs disease), subgroup vs whole sample.

"""Hypothesis card v1 (MVP) as Pydantic models: the single source of truth for the format, exported to JSON
Schema (docs/spec/hypothesis-card-spec.md; field names follow it).

Two layers, never mixed: the declared layer (`HypothesisCard`) comes only from the hypothesis text (the
normalizer); the verified layer (`Verification`) is produced by the pipeline (the verifier writes evidence,
code computes statuses and the evidence profile). Unestablished values are "unknown", never guessed."""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

UNKNOWN = "unknown"

HypothesisType = Literal["interventional", "mechanistic", "explanatory", "biomarker", "observational"]
Relation = Literal[
    "extends_lifespan_in", "shortens_lifespan_in", "no_lifespan_effect_in", "slows_aging_in", "improves_healthspan_in",
    "changes_biomarker", "predicts", "inhibits", "activates", "increases_expression", "decreases_expression",
    "promotes", "suppresses", "part_of", "associated_with", "affects_hallmark", "translates_to", "other"]
Role = Literal["premise", "mechanism", "analog", "outcome", "translation"]
# Method v3 (docs/archive/spec/method-v3.md): the place of a claim in the mechanism chain, from the intervention to the outcome
Link = Literal["delivery", "engagement", "pathway", "effect", "outcome"]
EdgeType = Literal["requires", "supports_if_true", "analog_of", "contradicts"]
Endpoint = Literal["lifespan", "healthspan", "biomarker", "disease", "mechanism", "unknown"]
System = Literal["cells", "worm", "fly", "yeast", "mouse", "rat", "human", "data_analysis", "unknown"]
DurationClass = Literal["weeks", "months", "years", "decades", "unknown"]
Hallmark = Literal[
    "genomic_instability", "telomere_attrition", "epigenetic_alterations", "loss_of_proteostasis",
    "disabled_macroautophagy", "deregulated_nutrient_sensing", "mitochondrial_dysfunction", "cellular_senescence",
    "stem_cell_exhaustion", "altered_intercellular_communication", "chronic_inflammation", "dysbiosis"]
Status = Literal["supported", "contested", "refuted", "unverified", "unresolved"]
Rung = Literal["none", "cells", "invertebrates", "mammals", "human_markers", "human_clinical"]
RUNGS: tuple[str, ...] = ("none", "cells", "invertebrates", "mammals", "human_markers", "human_clinical")
INHERITABLE = ("species", "strain")          # qualifiers a claim takes from PICO (spec 9, narrowed 2026-10-20)
MOLECULAR = ("inhibits", "activates", "increases_expression", "decreases_expression", "part_of")   # never inherit
ORGANISM_RELATIONS = ("extends_lifespan_in", "shortens_lifespan_in", "no_lifespan_effect_in", "slows_aging_in",
                      "improves_healthspan_in")  # the object is an organism
HUMAN_RUNGS = ("human_markers", "human_clinical")
RefusalType = Literal["type_mismatch", "direction_mismatch", "species_mismatch", "endpoint_mismatch", "inherited_mismatch",
                      "population_mismatch"]


# ---- declared layer ----

class Entity(BaseModel):
    label: str
    id: Optional[str] = None                     # resolved identifier (CHEBI, NCBITaxon, HGNC ...), optional at normalization
    hallmark: Optional[Hallmark] = None

    @model_validator(mode="before")
    @classmethod
    def _plain_label(cls, v):
        return {"label": v} if isinstance(v, str) else v       # `object: mouse` as in the verified-layer examples


class Claim(BaseModel):
    """One atomic claim: one relation, one context set, checkable by one source type."""
    id: str
    subject: Entity
    relation: Relation
    object: Entity
    qualifiers: dict[str, str] = Field(default_factory=dict)   # species, strain, sex, tissue, dose, age_at_start, comparator, direction, measure
    inherited_from_pico: list[str] = Field(default_factory=list)   # species / strain copied from PICO (spec 9)
    role: Role = "premise"                       # v13: derived by code from primary and stated_as (normalizer.derive_roles)
    link: Optional[Link] = None                  # v3: delivery (done and reached), engagement (target), pathway, effect, outcome
    source_span: str = ""                        # verbatim fragment of the hypothesis text (empty only for verifier-added claims)
    note: str = ""                               # e.g. why `other` was used
    # normalize_card/v13 (2026-11-12): the place in the chain (`link`) and the status in the author's reasoning are separate;
    # `role` is derived from them by code (normalizer.derive_roles) so that the rules reading it keep working
    primary: Optional[bool] = None               # the main outcome of the hypothesis (one claim with link outcome)
    stated_as: Optional[Literal["claimed", "known", "analogy"]] = None
    level: Optional[Literal["molecule", "cell", "tissue", "organ", "organism"]] = None   # reference only (not scored)
    sex_scope: Literal["any", "unspecified"] = "unspecified"   # `any`: the text claims the effect in at least one sex (an effect in one sex is enough)
    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, v):
        """An organelle is the cell level; any other value outside the list is left unknown (a card is not lost for it)."""
        if v in (None, "", "molecule", "cell", "tissue", "organ", "organism"):
            return v or None
        return "cell" if str(v).lower() in ("organelle", "subcellular") else None

    # normalize_card/v15 (docs/system/card.md, "Звенья"): a claim is on the chain of the main factor or a premise about the problem
    part: Optional[Literal["chain", "premise"]] = None
    premise_kind: Optional[Literal["population_state", "problem_mechanism"]] = None


class DeclaredAlternative(BaseModel):
    """An alternative the text names, structured like a claim (spec 4, 8c). `rejected`: the Y of a contrast
    "mainly X, not Y", verified like a claim; `listed`: only shown, never scored."""
    id: str
    subject: Entity
    relation: Relation
    object: Entity
    qualifiers: dict[str, str] = Field(default_factory=dict)
    inherited_from_pico: list[str] = Field(default_factory=list)
    source_span: str = ""
    stated_as: Literal["rejected", "listed"] = "listed"
    note: str = ""
    role: Literal["alternative"] = "alternative"   # not a declared role: lets the verifier treat it like a claim


class Edge(BaseModel):
    from_: str = Field(alias="from")
    to: str
    type: EdgeType
    model_config = {"populate_by_name": True}


class Population(BaseModel):
    taxon: Optional[str] = None
    label: str = UNKNOWN
    strain: str = UNKNOWN
    sex: str = UNKNOWN
    age_at_start: str = UNKNOWN                  # age of the population when the intervention starts (v15: as the text states it)
    condition: str = UNKNOWN                     # v15: the state the people or animals are selected for ("pre-sarcopenia")
    age_class: str = ""                          # v15: MeSH age group set by code from age_at_start (normalizer.age_class)
    span: str = ""                               # normalize_card/v12: the exact phrase of the text that states this field ("" before v12)

    @model_validator(mode="before")
    @classmethod
    def _old_age(cls, v):
        """Cards written before 2026-10-19 used `age` (spec 4 renamed it)."""
        if isinstance(v, dict) and "age" in v:
            v = dict(v)
            age = v.pop("age")
            if not v.get("age_at_start") or v.get("age_at_start") == UNKNOWN:
                v["age_at_start"] = age
        return v


Route = Literal["diet", "water", "oral", "injection", "topical", "other", "unknown"]


class Intervention(BaseModel):
    type: Literal["compound", "gene", "diet", "procedure", "other"] = "other"
    label: str
    id: Optional[str] = None
    regimen: str = UNKNOWN
    route: Route = "unknown"                     # diet / water: mixed into food or drinking water
    span: str = ""                               # normalize_card/v12: the exact phrase of the text that states this field ("" before v12)


class Comparator(BaseModel):
    type: str = UNKNOWN                          # placebo | untreated | standard_care | wild_type | monotherapy | active_drug | chronological_age | other
    label: str = UNKNOWN
    span: str = ""                               # normalize_card/v12: the exact phrase of the text that states this field ("" before v12)

    @model_validator(mode="before")
    @classmethod
    def _plain(cls, v):
        return {"type": v, "label": v} if isinstance(v, str) else v   # `comparator: unknown`


class Outcome(BaseModel):
    endpoint: Endpoint = "unknown"
    metric: str = UNKNOWN
    direction: str = UNKNOWN                     # v13: increase | decrease | improve | worsen | unknown
    span: str = ""                               # normalize_card/v12: the exact phrase of the text that states this field ("" before v12)


class Pico(BaseModel):
    population: Population = Field(default_factory=Population)
    intervention: list[Intervention] = Field(default_factory=list)
    comparator: Comparator = Field(default_factory=Comparator)
    background: list[Intervention] = Field(default_factory=list)   # v13: what every group receives alike (not an intervention)
    outcome: Outcome = Field(default_factory=Outcome)
    time: str = UNKNOWN


class DecisiveExperiment(BaseModel):
    system: System = "unknown"
    endpoint: str = UNKNOWN
    duration_class: DurationClass = "unknown"
    # v3: the experiment stated in the text (for registry trials filled by code from the registry fields)
    design: Literal["rct", "cluster_rct", "single_arm", "pilot", "observational", "other", "unknown"] = "unknown"
    control: Literal["placebo", "active", "usual_care", "none", "unknown"] = "unknown"
    n_planned: Optional[int] = None
    primary_outcome: str = UNKNOWN
    primary_outcomes: list[str] = Field(default_factory=list)      # v13: each primary outcome with its time frame
    duration: str = UNKNOWN                      # v13: as the text gives it; duration_class is computed from it by code
    registry: dict = Field(default_factory=dict) # v13: design fields of a registry text parsed by code (allocation, model, masking, arms)
    arms: list[str] = Field(default_factory=list)   # v15: the arms or test manipulations the text names (an added antigen, a knockout)
    span: str = ""                               # normalize_card/v12: the exact phrase of the text that states this field ("" before v12)


AlternativeFate = Literal["eliminated", "weakened", "unchanged"]


class ProposedAlternative(BaseModel):
    """v3: a competing explanation of the same phenomenon, proposed by a model from the hypothesis and the literature found
    (not declared by the text). Its support is checked like a claim; without records it weighs nothing. `on_positive` and
    `on_negative`: what the stated decisive experiment does to it under each outcome."""
    id: str
    subject: Entity
    relation: Relation
    object: Entity
    qualifiers: dict[str, str] = Field(default_factory=dict)
    rationale: str = ""
    support_pmids: list[str] = Field(default_factory=list)
    on_positive: AlternativeFate = "unchanged"
    on_negative: AlternativeFate = "unchanged"
    role: Literal["alternative"] = "alternative"

    @model_validator(mode="after")
    def _not_both(self):
        if self.on_positive == "eliminated" and self.on_negative == "eliminated":
            raise ValueError("an alternative cannot be eliminated under both outcomes")
        return self


class HypothesisCard(BaseModel):
    """Declared layer: only what the hypothesis text states."""
    id: str
    raw_id: str = ""
    hypothesis_type: HypothesisType
    claim_plain: str
    pico: Pico = Field(default_factory=Pico)
    claims: list[Claim] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    declared_novelty: str = UNKNOWN
    decisive_experiment: DecisiveExperiment = Field(default_factory=DecisiveExperiment)
    declared_alternatives: list[DeclaredAlternative] = Field(default_factory=list)
    proposed_alternatives: list[ProposedAlternative] = Field(default_factory=list)   # v3, model-proposed (separate step)
    declared_decision_criteria: str = UNKNOWN
    risks: list[str] = Field(default_factory=list)
    # normalize_card/v10 (method-v3.md section 13): the role of AI in the hypothesis, with the verbatim span that states it;
    # code sets "none" when the span is not in the text. An ordinal indicator of the investor profile, not part of P or V.
    ai_role: Literal["none", "analysis", "in_the_loop", "intervention"] = "none"
    ai_role_span: str = ""
    # normalize_card/v12 (2026-11-12, user decision): core fields whose value has no verbatim span after the rounds; the value is
    # kept and shown as "from the text, not anchored" (docs/system/card.md)
    unanchored: list[str] = Field(default_factory=list)
    expected_effect: Optional[dict] = None       # v13: {size, compared_to, time_point, span} when the text names a size
    author_refs: list[str] = Field(default_factory=list)          # v13: PMIDs / DOIs named in the text (code)
    # v15: the thing whose consequences the hypothesis states (the chain starts from it) and the disease or ageing process
    # it is about; {label, kind: intervention | exposure | condition | process, span} and {label, span, mesh}
    main_factor: Optional[dict] = None
    topic: Optional[dict] = None

    @field_validator("risks", mode="before")
    @classmethod
    def _plain_risks(cls, v):
        """normalize_card/v15 sometimes writes a risk as an object ({risk, span}); keep its text (3 of 90 cards were lost)."""
        if not isinstance(v, list):
            return v
        return [x if isinstance(x, str) else str(x.get("risk") or x.get("label") or x.get("text") or next(iter(x.values()), ""))
                if isinstance(x, dict) else str(x) for x in v]

    @field_validator("declared_alternatives", mode="before")
    @classmethod
    def _plain_alternatives(cls, v):
        """A bare string (an alternative only listed by the text) becomes a `listed` entry."""
        if not isinstance(v, list):
            return v
        return [{"id": f"a{i}", "subject": {"label": x}, "relation": "other", "object": {"label": UNKNOWN},
                 "stated_as": "listed", "note": "listed as plain text"} if isinstance(x, str) else x
                for i, x in enumerate(v, start=1)]

    @property
    def outcome_claim(self) -> Optional[Claim]:
        return next((c for c in self.claims if c.role == "outcome"), None)

    @property
    def rejected_alternatives(self) -> list[DeclaredAlternative]:
        return [a for a in self.declared_alternatives if a.stated_as == "rejected"]


class RawHypothesis(BaseModel):
    id: str
    origin: Literal["external", "internal", "expert"] = "external"
    text: str
    received_at: str = ""
    generator: Optional[str] = None
    parent_id: Optional[str] = None


class Admission(BaseModel):
    raw_id: str
    decision: Literal["accepted", "needs_refinement", "not_a_hypothesis"]
    missing_critical: list[str] = Field(default_factory=list)
    context_specificity: int = 0
    known_result: Optional[bool] = None          # set after verification (spec 4a)
    reason: str = ""
    flags: list[str] = Field(default_factory=list)   # unmapped_relation: the outcome claim is still `other` (spec 5)


# ---- verified layer ----

class ProgramInfo(BaseModel):
    """A standardized, pre-registered multi-site program that publishes negative results (ITP, CITP)."""
    name: str
    sites_with_effect: Optional[int] = None


class EvidenceRecord(BaseModel):
    source: str                                  # PubMed | DrugAge | OpenGenes | ClinicalTrials.gov | GEO | ...
    record_id: str
    epistemic_type: Literal["A_text", "B_curated", "C_measurement", "D_machine", "E_quality", "F_plans"] = "A_text"
    study_type: str = UNKNOWN                    # primary_experiment | rct | open_label_pilot | observational | review | ...
    lab_or_cohort: str = ""                      # robustness counts distinct values
    derived_from: str = ""                       # set for reviews / reanalyses / curated copies: does not add robustness
    linked_pmid: str = ""                        # curated records: the paper they come from
    species: str = UNKNOWN
    strain: str = UNKNOWN                        # as reported: UM-HET3, C57BL/6J, N2 ...
    sex: Literal["male", "female", "both", "unknown"] = "unknown"   # of the animals or participants of the finding
    dose: str = UNKNOWN                          # as reported
    age_at_start: str = UNKNOWN                  # as reported
    human_rungs: list[Literal["human_markers", "human_clinical"]] = Field(default_factory=list)   # human records (spec 8)
    system: str = ""                             # in_vivo | ex_vivo | in_vitro (empty: in vivo)
    location: str = ""
    quote: str = ""
    quote_role: Literal["finding", "background", "speculation"] = "finding"
    metric: str = UNKNOWN
    effect_percent: Optional[float] = None       # e.g. % change of median lifespan, when extracted
    endpoint: Endpoint = "unknown"               # what the finding measures (lifespan, healthspan, biomarker, disease)
    effect: Literal["increase", "decrease", "no_effect", "unknown"] = "unknown"   # direction of a lifespan finding
    qualifiers_match: dict[str, str] = Field(default_factory=dict)   # species/sex/age_at_start/dose/comparator: yes|no|n/a; intervention_match
    marker_validation: Literal["validated_surrogate", "exploratory", "n/a"] = "n/a"
    program: Optional[ProgramInfo] = None
    model_type: Literal["", "disease_model", "aging_model"] = ""   # the animals of the finding had a disease (named in `disease`) or accelerated ageing
    disease: str = ""                            # the disease or model: valid only with `disease_evidence`
    disease_evidence: str = ""                   # the sentence (or the curated strain field) where the disease is named
    strata: list[str] = Field(default_factory=list)  # strata the protocol fixed in advance (`sex` in ITP and CITP): a result in one of them is not a post hoc subgroup
    flags: list[str] = Field(default_factory=list)   # retracted, preprint, conflict_of_interest, small_n, open_label, subgroup_only, short_lived_controls, disease_model, special_diet
    fields: dict[str, Union[str, float, int]] = Field(default_factory=dict)   # curated-record fields (e.g. DrugAge row)
    # v3 extraction, from the whole abstract (docs/archive/spec/method-v3.md, section 2); numbers are checked verbatim by code
    design: Literal["rct", "non_randomised", "observational", "animal", "cells", "review", "meta_analysis", "other",
                    "unknown"] = "unknown"
    review_kind: str = ""                         # systematic | narrative, from PubMed publication types (2026-11-11)
    certainty: str = ""                           # GRADE certainty of a meta-analysis from its abstract (2026-11-11)
    n_total: Optional[int] = None
    n_quote: str = ""                            # the verbatim phrase that gives n_total
    comparison: Literal["between_groups", "within_group", "none", "unknown"] = "unknown"
    effect_reported: str = ""                    # the verbatim effect size ("+2.4 kg", "RR 0.79 (0.65-0.96)")
    effect_class: Literal["none", "small", "medium", "large", "unclear"] = "unclear"
    blinding: Literal["double_blind", "single_blind", "assessor_blind", "open", "not_reported", "not_applicable",
                      "unknown"] = "unknown"      # verify_claim/v11 (2026-11-08): of the study the finding comes from
    outcome_subjective: Optional[bool] = None    # verify_claim/v11: the outcome of the quote is self-reported or rated
    reports_trial: str = ""                      # a review restating one trial's result: the trial as named
    primary_record: str = ""                     # the record id of that trial's own paper, when found
    retrieved_at: str = ""
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _old_sexes(cls, v):
        """Records written before 2026-10-20 had a list `sexes` instead of `sex`."""
        if isinstance(v, dict) and "sexes" in v:
            v = dict(v)
            sexes = set(v.pop("sexes") or [])
            if "sex" not in v:
                v["sex"] = "both" if sexes >= {"male", "female"} else next(iter(sexes)) if sexes else "unknown"
        return v

    @property
    def sexes(self) -> set[str]:
        return {"male", "female"} if self.sex == "both" else {self.sex} if self.sex in ("male", "female") else set()


class Refusal(BaseModel):
    type: RefusalType
    record_id: str = ""
    quote: str = ""
    notes: str = ""


class ClaimVerification(BaseModel):
    id: str                                      # claim id (declared) or an added analog id (a1, ...)
    status: Optional[Status] = None              # computed by code from the records when None
    rung: Optional[Rung] = None                  # the evidence rung of this claim, if the verifier sets it
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    counterevidence: list[EvidenceRecord] = Field(default_factory=list)
    refusals: list[Refusal] = Field(default_factory=list)
    no_stance: list[EvidenceRecord] = Field(default_factory=list)   # v3: findings returned with stance neither; not scored,
    # kept for the sensitivity analysis of the v3 calibration (the verifier's recall is about 0.6, extraction-gold-v9)
    unresolved: bool = False                     # entities could not be mapped
    contrast: dict[str, str] = Field(default_factory=dict)   # outcome of a contrast: alternative, x_status, y_status
    flags: list[str] = Field(default_factory=list)            # e.g. contrast_unchecked
    rung_status: dict[str, str] = Field(default_factory=dict)  # human claims: status per human rung (spec 8)
    notes: str = ""
    claim: Optional[Claim] = Field(default=None, validation_alias=AliasChoices("claim", "added_claim"))
    # claims added by the verifier (analogs an<N>, verified layer only); `added_claim` is the older name

    @model_validator(mode="before")
    @classmethod
    def _short_claim(cls, v):
        """The short form `claim: {subject, relation, object, qualifiers}` (examples, spec 7): id from the record,
        role analog."""
        if isinstance(v, dict):
            key = "claim" if "claim" in v else "added_claim" if "added_claim" in v else None
            if key and isinstance(v[key], dict):
                v = {**v, key: {"id": v.get("id"), "role": "analog", **v[key]}}
        return v


class Conflict(BaseModel):
    rung: Rung
    for_: list[str] = Field(default_factory=list, alias="for")
    against: list[str] = Field(default_factory=list)
    against_is_program: bool = False
    model_config = {"populate_by_name": True}


class EvidenceProfile(BaseModel):
    gate: Literal["pass", "filtered"] = "pass"
    gate_reason: str = ""
    effect_level: Rung = "none"
    effect_level_note: str = ""                  # e.g. "human_clinical (observational only)", "human_markers (exploratory only)"
    effect_contested: list[Rung] = Field(default_factory=list)
    robustness: Literal["single", "replicated"] = "single"
    multi_site_program: dict[str, str] = Field(default_factory=lambda: {"tested": "no"})
    no_literature: bool = False                  # no evidence and no counterevidence record for any claim: novelty stays unknown
    mechanism: Literal["supported", "partial", "unverified", "refuted"] = "unverified"
    disease_models: int = 0                      # records from disease models (analogs of type disease_model): not in effect_level
    aging_models: int = 0                        # records from accelerated-ageing models: not counted yet
    intervention_match: str = ""
    next_step: str = ""
    conflicts: list[Conflict] = Field(default_factory=list)


class Alternative(BaseModel):
    """An alternative explanation (spec 8c). ids: a<N> declared, alt<N> added by the pipeline."""
    id: str
    type: str                                    # checklist id (food_intake ...), "declared", "competitor"
    source: Literal["checklist", "proximity", "debate", "declared", "expert"]
    status: Literal["open", "excluded_by_evidence", "supported", "contested", "refuted", "unverified", "unresolved"] = "open"
    explanation: str = ""
    discriminating_design: str = ""
    ref: str = ""                                # competitor hypothesis id
    record_id: str = ""                          # the study with the discriminating control, when excluded
    quote: str = ""


class Verification(BaseModel):
    card_id: str
    claims: list[ClaimVerification] = Field(default_factory=list)
    evidence_profile: Optional[EvidenceProfile] = None
    known_result: bool = False
    alternatives: list[Alternative] = Field(default_factory=list)
    prediction_table: list[dict] = Field(default_factory=list)     # stage C (spec 8c)
    decision_criteria: dict[str, str] = Field(default_factory=dict)   # stage C
    searched_pmids: list[str] = Field(default_factory=list)        # abstracts the verifier read (checklist check)
    declared_vs_verified: list[str] = Field(default_factory=list)


# ---- expert layer (spec 7a): expert decisions; never edits the declared or verified layer ----

ExpertPoint = Literal["profile", "pairwise", "evidence_conflict", "objection", "alternative", "variant", "portfolio",
                      "disease_context"]


class ExpertDecision(BaseModel):
    id: str
    by: str = ""                                 # name or role
    at: str = ""                                 # date
    point: ExpertPoint
    target: Union[str, list[str]]                # claim, objection, alternative, variant or hypothesis id; pairwise: [H-A, H-B]
    decision: str                                # e.g. accept | reject | prefer H-A | take into work
    rationale: str = ""
    source: Optional[str] = None                 # e.g. "PMID:..."; only a source can change a claim status
    hypothesis: Optional[str] = None             # the card a claim-level target belongs to (in a run-level file)
    profile: Optional[str] = None                # pairwise: the preference profile it applies to (None: every profile)


class ExpertLayer(BaseModel):
    """The expert file of a run: decisions, and hypotheses written by the expert (origin: expert)."""
    decisions: list[ExpertDecision] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)


def json_schema() -> dict:
    """JSON Schema of the declared card and the verified layer (for people and other tools)."""
    return {"HypothesisCard": HypothesisCard.model_json_schema(by_alias=True),
            "Verification": Verification.model_json_schema(by_alias=True),
            "RawHypothesis": RawHypothesis.model_json_schema(), "Admission": Admission.model_json_schema(),
            "ExpertLayer": ExpertLayer.model_json_schema()}

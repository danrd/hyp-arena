"""Hypothesis card v1 (MVP) as Pydantic models: the single source of truth for the format, exported to JSON
Schema (docs/spec/hypothesis-card-spec.md; field names follow it).

Two layers, never mixed: the declared layer (`HypothesisCard`) comes only from the hypothesis text (the
normalizer); the verified layer (`Verification`) is produced by the pipeline (the verifier writes evidence,
code computes statuses and the evidence profile). Unestablished values are "unknown", never guessed."""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

UNKNOWN = "unknown"

HypothesisType = Literal["interventional", "mechanistic", "biomarker", "observational"]
Relation = Literal[
    "extends_lifespan_in", "shortens_lifespan_in", "no_lifespan_effect_in", "improves_healthspan_in",
    "changes_biomarker", "predicts", "inhibits", "activates", "increases_expression", "decreases_expression",
    "promotes", "suppresses", "part_of", "associated_with", "affects_hallmark", "translates_to", "other"]
Role = Literal["premise", "mechanism", "analog", "outcome", "translation"]
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


# ---- declared layer ----

class Entity(BaseModel):
    label: str
    id: Optional[str] = None                     # resolved identifier (CHEBI, NCBITaxon, HGNC ...), optional at normalization
    hallmark: Optional[Hallmark] = None


class Claim(BaseModel):
    """One atomic claim: one relation, one context set, checkable by one source type."""
    id: str
    subject: Entity
    relation: Relation
    object: Entity
    qualifiers: dict[str, str] = Field(default_factory=dict)   # species, strain, sex, tissue, dose, age_at_start, comparator, direction, measure
    role: Role
    source_span: str = ""                        # verbatim fragment of the hypothesis text (empty only for verifier-added claims)
    note: str = ""                               # e.g. why `other` was used


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
    age: str = UNKNOWN
    age_at_start: str = UNKNOWN


class Intervention(BaseModel):
    type: Literal["compound", "gene", "diet", "procedure", "other"] = "other"
    label: str
    id: Optional[str] = None
    regimen: str = UNKNOWN


class Comparator(BaseModel):
    type: str = UNKNOWN                          # placebo | untreated | standard_care | wild_type | monotherapy | active_drug | chronological_age | other
    label: str = UNKNOWN


class Outcome(BaseModel):
    endpoint: Endpoint = "unknown"
    metric: str = UNKNOWN


class Pico(BaseModel):
    population: Population = Field(default_factory=Population)
    intervention: list[Intervention] = Field(default_factory=list)
    comparator: Comparator = Field(default_factory=Comparator)
    outcome: Outcome = Field(default_factory=Outcome)
    time: str = UNKNOWN


class DecisiveExperiment(BaseModel):
    system: System = "unknown"
    endpoint: str = UNKNOWN
    duration_class: DurationClass = "unknown"


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
    declared_alternatives: list[str] = Field(default_factory=list)
    declared_decision_criteria: str = UNKNOWN
    risks: list[str] = Field(default_factory=list)

    @property
    def outcome_claim(self) -> Optional[Claim]:
        return next((c for c in self.claims if c.role == "outcome"), None)


class RawHypothesis(BaseModel):
    id: str
    origin: Literal["external", "internal"] = "external"
    text: str
    received_at: str = ""
    generator: Optional[str] = None
    parent_id: Optional[str] = None


class Admission(BaseModel):
    raw_id: str
    decision: Literal["accepted", "needs_refinement", "not_a_hypothesis"]
    missing_critical: list[str] = Field(default_factory=list)
    context_specificity: int = 0
    reason: str = ""


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
    system: str = ""                             # in_vivo | ex_vivo | in_vitro (empty: in vivo)
    location: str = ""
    quote: str = ""
    quote_role: Literal["finding", "background", "speculation"] = "finding"
    metric: str = UNKNOWN
    effect_percent: Optional[float] = None       # e.g. % change of median lifespan, when extracted
    sexes: list[Literal["male", "female"]] = Field(default_factory=list)
    endpoint: Endpoint = "unknown"               # what the finding measures (lifespan, healthspan, biomarker, disease)
    qualifiers_match: dict[str, str] = Field(default_factory=dict)   # species/sex/age_at_start/dose/comparator: yes|no|n/a; intervention_match
    marker_validation: Literal["validated_surrogate", "exploratory", "n/a"] = "n/a"
    program: Optional[ProgramInfo] = None
    flags: list[str] = Field(default_factory=list)   # retracted, preprint, conflict_of_interest, small_n, open_label, subgroup_only, short_lived_controls
    fields: dict[str, Union[str, float, int]] = Field(default_factory=dict)   # curated-record fields (e.g. DrugAge row)
    retrieved_at: str = ""
    notes: str = ""


class Refusal(BaseModel):
    type: str                                    # endpoint_mismatch | species_mismatch | direction | type ...
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
    unresolved: bool = False                     # entities could not be mapped
    notes: str = ""
    added_claim: Optional[Claim] = None          # analogs added by the verifier (verified layer only)


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
    mechanism: Literal["supported", "partial", "unverified", "refuted"] = "unverified"
    intervention_match: str = ""
    next_step: str = ""
    conflicts: list[Conflict] = Field(default_factory=list)


class Verification(BaseModel):
    card_id: str
    claims: list[ClaimVerification] = Field(default_factory=list)
    evidence_profile: Optional[EvidenceProfile] = None
    known_result: bool = False
    declared_vs_verified: list[str] = Field(default_factory=list)


def json_schema() -> dict:
    """JSON Schema of the declared card and the verified layer (for people and other tools)."""
    return {"HypothesisCard": HypothesisCard.model_json_schema(by_alias=True),
            "Verification": Verification.model_json_schema(by_alias=True),
            "RawHypothesis": RawHypothesis.model_json_schema(), "Admission": Admission.model_json_schema()}

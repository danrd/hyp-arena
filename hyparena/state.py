"""Graph state and the records it holds. Hypotheses and matches are append-only."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

Status = Literal["new", "normalized", "active", "rejected", "merged"]


class Provenance(BaseModel):
    """Which model, prompt and strategy produced an artifact."""
    family: str                  # e.g. "gemini"; "unknown" or "human" when not known
    model_version: str           # exact identifier of what answered
    role: str
    template: str = ""
    prompt_version: str = ""
    strategy: str = ""
    call_id: str = ""


class Card(BaseModel):
    """What the hypothesis DECLARES, extracted by the normalizer. The field set comes from the card
    schema (configs/card.yaml, a draft); nothing here is verified."""
    schema_version: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)          # required fields the text does not state
    search_queries: list[str] = Field(default_factory=list)  # suggested literature queries

    def get(self, name: str, default: Any = "") -> Any:
        value = self.fields.get(name)
        return value if value not in (None, "", []) else default

    def filled(self) -> dict[str, Any]:
        return {k: v for k, v in self.fields.items() if v not in (None, "", [])}


class Evidence(BaseModel):
    """One piece of retrieved evidence, uniform across sources. Only `source` and `record_id` are
    required; the rest is filled when the source provides it."""
    source: str                                  # connector, e.g. "europepmc"
    record_id: str                               # stable id inside the source (e.g. MED:12345)
    title: str = ""
    text: str = ""                               # excerpt shown to reviewers and judges
    url: str = ""
    publication_date: Optional[str] = None       # ISO date; the basis for "as of date T" filtering
    retrieved_at: str = ""
    query: str = ""
    tier: Optional[int] = None                   # 1 curated ... 4 preprint (see docs/architecture.md)
    study_type: str = ""
    species: str = ""
    license: str = ""
    entity_ids: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)   # e.g. "retracted"; flagged records are not used
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return "retracted" not in self.flags


def usable(evidence: list["Evidence"]) -> list["Evidence"]:
    """Evidence that reviewers and judges may see (retracted records are kept for audit, not shown)."""
    return [e for e in evidence if e.usable]


class Review(BaseModel):
    kind: Literal["initial", "full", "deep"]
    scores: dict[str, float] = Field(default_factory=dict)
    passed: bool = True
    notes: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    provenance: Provenance


class Hypothesis(BaseModel):
    id: str
    text: str                    # the original free-form text, never modified
    provenance: Provenance
    parents: list[str] = Field(default_factory=list)
    status: Status = "new"
    card: Optional[Card] = None
    evidence: list[Evidence] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)
    cluster: Optional[int] = None
    merged_into: Optional[str] = None


class JudgeVerdict(BaseModel):
    provenance: Provenance
    order: list[str] = Field(default_factory=list)          # ids as shown: first, second
    winner: dict[str, str] = Field(default_factory=dict)    # criterion -> winning hypothesis id
    rationale: str = ""
    parse_ok: bool = True


class Match(BaseModel):
    a: str
    b: str
    mode: Literal["single", "debate"] = "single"
    judges: list[JudgeVerdict] = Field(default_factory=list)
    contested: bool = False
    winners: dict[str, Optional[str]] = Field(default_factory=dict)   # criterion -> id, None on a tie


class Rating(BaseModel):
    score: float = 0.0           # log-strength (Bradley-Terry)
    se: float = 10.0
    games: int = 0


class Criterion(BaseModel):
    name: str
    description: str = ""
    weight: float = 1.0


class PlanConfig(BaseModel):
    preferences: str = ""
    attributes: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)    # from configs/criteria.yaml, not from the LLM
    criteria_version: str = ""

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.criteria]

    @property
    def weights(self) -> dict[str, float]:
        total = sum(c.weight for c in self.criteria) or 1.0
        return {c.name: c.weight / total for c in self.criteria}


def merge_dicts(old: Optional[dict], new: Optional[dict]) -> dict:
    return {**(old or {}), **(new or {})}


class GraphState(TypedDict, total=False):
    goal: str
    plan: PlanConfig
    hypotheses: Annotated[dict[str, Hypothesis], merge_dicts]
    ratings: dict[str, dict[str, Rating]]            # criterion -> id -> Rating, replaced each tournament
    matches: Annotated[list[Match], operator.add]
    feedback: dict[str, str]                         # meta-review text per agent
    cycle: int
    next: str
    top_history: list[list[str]]
    report: dict


def initial_state(goal: str, hypotheses: Optional[list[Hypothesis]] = None) -> GraphState:
    """Start state; `hypotheses` preloads imported ones (status `new`), which then go through
    normalization, review and the tournament like generated ones."""
    return GraphState(goal=goal, hypotheses={h.id: h for h in hypotheses or []}, ratings={}, matches=[],
                      feedback={}, cycle=0, top_history=[])

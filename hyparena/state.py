"""Graph state and the records it holds. Hypotheses and matches are append-only."""
from __future__ import annotations

import operator
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

AXES = ("promise", "feasibility")

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


class NormalizedRecord(BaseModel):
    claim: str = ""
    mechanism: str = ""
    prediction: str = ""
    experiment: str = ""
    falsification: str = ""
    known: str = ""
    assumptions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)   # required fields still missing


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
    record: Optional[NormalizedRecord] = None
    reviews: list[Review] = Field(default_factory=list)
    cluster: Optional[int] = None
    merged_into: Optional[str] = None


class JudgeVerdict(BaseModel):
    provenance: Provenance
    order: list[str] = Field(default_factory=list)          # ids as shown: first, second
    winner: dict[str, str] = Field(default_factory=dict)    # axis -> winning hypothesis id
    rationale: str = ""
    parse_ok: bool = True


class Match(BaseModel):
    a: str
    b: str
    mode: Literal["single", "debate"] = "single"
    judges: list[JudgeVerdict] = Field(default_factory=list)
    contested: bool = False
    winners: dict[str, Optional[str]] = Field(default_factory=dict)   # axis -> id, None on a tie


class Rating(BaseModel):
    score: float = 0.0           # log-strength (Bradley-Terry)
    se: float = 10.0
    games: int = 0


class PlanConfig(BaseModel):
    preferences: str = ""
    attributes: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    axis_weights: dict[str, float] = Field(default_factory=lambda: {"promise": 0.5, "feasibility": 0.5})


def merge_dicts(old: Optional[dict], new: Optional[dict]) -> dict:
    return {**(old or {}), **(new or {})}


class GraphState(TypedDict, total=False):
    goal: str
    plan: PlanConfig
    hypotheses: Annotated[dict[str, Hypothesis], merge_dicts]
    ratings: dict[str, dict[str, Rating]]            # axis -> id -> Rating, replaced each tournament
    matches: Annotated[list[Match], operator.add]
    feedback: dict[str, str]                         # meta-review text per agent
    cycle: int
    next: str
    top_history: list[list[str]]
    report: dict


def initial_state(goal: str) -> GraphState:
    return GraphState(goal=goal, hypotheses={}, ratings={}, matches=[], feedback={}, cycle=0,
                      top_history=[])

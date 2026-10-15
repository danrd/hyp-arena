"""Configurable parts of the comparison: the criteria judges compare on and the hypothesis card schema.

Both are loaded from YAML so that changing them does not need code changes (the card format is a draft)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional, Union

import yaml
from pydantic import BaseModel

from hyparena.aggregate import centroid_weights, groups_of
from hyparena.state import Criterion

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


class CardField(BaseModel):
    name: str
    type: Literal["text", "list"] = "text"
    required: bool = False
    description: str = ""


class CardSchema(BaseModel):
    version: str
    fields: list[CardField]

    @property
    def required(self) -> list[str]:
        return [f.name for f in self.fields if f.required]

    def example_json(self, extra: dict | None = None) -> str:
        """A one-line JSON skeleton of the card, used in prompts (and parsed by the fake LLM)."""
        skeleton = {f.name: ([] if f.type == "list" else "") for f in self.fields}
        return json.dumps({**skeleton, **(extra or {})}, ensure_ascii=False)


class CriteriaSet(BaseModel):
    version: str
    criteria: list[Criterion]
    # Order of importance instead of numeric weights (aggregation by МРСП, hyparena/aggregate.py): names from
    # most to least important; a nested list is a group of equally important criteria.
    importance: Optional[list[Union[str, list[str]]]] = None


def load_criteria(path: str | Path = CONFIGS / "criteria.yaml") -> CriteriaSet:
    """Criteria from YAML. With an importance order, each criterion's weight becomes its expected weight
    under that order (rank-order centroid), used where one number is needed (pair selection)."""
    cs = CriteriaSet(**yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    if cs.importance:
        groups = groups_of(cs.importance)
        named = [c for g in groups for c in g]
        if sorted(named) != sorted(c.name for c in cs.criteria):
            raise ValueError(f"importance must list every criterion exactly once: {named}")
        w = centroid_weights(groups)
        cs.criteria = [c.model_copy(update={"weight": w[c.name]}) for c in cs.criteria]
    return cs


def load_card_schema(path: str | Path = CONFIGS / "card.yaml") -> CardSchema:
    return CardSchema(**yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def verdict_example(criteria: list[Criterion]) -> str:
    """One-line JSON skeleton of a judge's reply: 1 or 2 per criterion, then a rationale."""
    return json.dumps({**{c.name: 1 for c in criteria}, "rationale": "<one or two sentences>"})

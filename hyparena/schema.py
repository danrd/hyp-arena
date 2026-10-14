"""Configurable parts of the comparison: the criteria judges compare on and the hypothesis card schema.

Both are loaded from YAML so that changing them does not need code changes (the card format is a draft)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

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


def load_criteria(path: str | Path = CONFIGS / "criteria.yaml") -> CriteriaSet:
    return CriteriaSet(**yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def load_card_schema(path: str | Path = CONFIGS / "card.yaml") -> CardSchema:
    return CardSchema(**yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def verdict_example(criteria: list[Criterion]) -> str:
    """One-line JSON skeleton of a judge's reply: 1 or 2 per criterion, then a rationale."""
    return json.dumps({**{c.name: 1 for c in criteria}, "rationale": "<one or two sentences>"})

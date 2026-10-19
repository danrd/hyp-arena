"""Normalizer: hypothesis text → declared card (card spec section 9). The LLM parses; code validates the schema,
the closed vocabulary, exactly one outcome claim and that every source_span is verbatim, and asks again with
the problems when something fails."""
from __future__ import annotations

import typing
from typing import Optional

from pydantic import ValidationError

from hyparena.card.llm import ask
from hyparena.card.models import Hallmark, HypothesisCard, Relation
from hyparena.card.rules import mark_inherited, validate_card

TEMPLATE = ("normalize_card", "v3")


def _problems(value: dict, raw_text: str, card_id: str) -> tuple[Optional[HypothesisCard], list[str]]:
    try:
        card = HypothesisCard.model_validate({**value, "id": card_id, "raw_id": card_id})
    except ValidationError as e:
        return None, [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:12]]
    return mark_inherited(card), validate_card(card, raw_text)


def normalize(client, family: str, raw_text: str, card_id: str, log: Optional[list] = None,
              rounds: int = 3) -> tuple[Optional[HypothesisCard], list[str]]:
    """(card or None, remaining problems)."""
    variables = {"text": raw_text, "relations": ", ".join(typing.get_args(Relation)),
                 "hallmarks": ", ".join(typing.get_args(Hallmark))}
    value, _ = ask(client, role="normalize_card", family=family, template=TEMPLATE[0], version=TEMPLATE[1],
                   variables=variables, validate=lambda v: _problems(v, raw_text, card_id)[1], rounds=rounds, log=log)
    if value is None:
        return None, ["no valid JSON from the normalizer"]
    card, problems = _problems(value, raw_text, card_id)
    if card is not None and problems:                  # drop claims whose span is not verbatim, keep the rest
        bad = {p.split(":")[0] for p in problems if "source_span" in p}
        if bad and len(bad) < len(card.claims):
            card.claims = [c for c in card.claims if c.id not in bad]
            card.edges = [e for e in card.edges if e.from_ not in bad and e.to not in bad]
            problems = validate_card(card, raw_text)
    return card, problems

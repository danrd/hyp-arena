"""Normalizer: hypothesis text → declared card (card spec section 9). The LLM parses; code validates the schema,
the closed vocabulary, exactly one outcome claim and that every source_span is verbatim, and asks again with
the problems when something fails."""
from __future__ import annotations

import re
import typing
from typing import Optional

from pydantic import ValidationError

from hyparena.card.llm import ask
from hyparena.card.models import Hallmark, HypothesisCard, Relation
from hyparena.card.canonical import canonicalize
from hyparena.card.rules import mark_inherited, set_sex_scope, validate_card

TEMPLATE = ("normalize_card", "v6")       # v6 adopted 2026-10-29 by the user's decision, see docs/rules-method.md

# relations an outcome claim can take, with the words that point to them (for the re-parse hint, spec 5)
OUTCOME_RELATIONS = {
    "extends_lifespan_in": "extends increases lifespan longevity survival live longer",
    "shortens_lifespan_in": "shortens decreases lifespan survival mortality",
    "no_lifespan_effect_in": "no effect lifespan survival",
    "slows_aging_in": "slows delays aging ageing age-related changes decline pathology",
    "improves_healthspan_in": "improves healthspan function frailty strength mobility health",
    "changes_biomarker": "changes lowers raises reduces increases biomarker marker level clock blood",
    "predicts": "predicts marker risk outcome mortality",
    "promotes": "promotes causes drives induces increases",
    "suppresses": "suppresses reduces prevents inhibits lowers protects",
    "affects_hallmark": "hallmark senescence autophagy proteostasis mitochondria inflammation",
    "associated_with": "associated linked correlated",
}


def nearest_relations(text: str, k: int = 4) -> list[str]:
    """Vocabulary relations whose cue words overlap most with the claim's note and span."""
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    score = {r: len(words & set(cues.split())) for r, cues in OUTCOME_RELATIONS.items()}
    return sorted(score, key=lambda r: (-score[r], list(OUTCOME_RELATIONS).index(r)))[:k]


def _closed_fields(value: dict) -> dict:
    """Values outside the closed lists of the stated experiment ("no intervention" for control, say) become "unknown"
    instead of failing the whole card (normalizer-v8 check: one of 30 cards was lost that way). Only these fields."""
    import typing as _t
    from hyparena.card.models import DecisiveExperiment
    e = value.get("decisive_experiment")
    if not isinstance(e, dict):
        return value
    fixed = dict(e)
    for name, field in DecisiveExperiment.model_fields.items():
        allowed = _t.get_args(field.annotation)
        if allowed and all(isinstance(x, str) for x in allowed) and name in fixed and fixed[name] not in allowed:
            fixed[name] = "unknown" if "unknown" in allowed else allowed[-1]
    return {**value, "decisive_experiment": fixed}


ENDPOINT_BY_RELATION = {"changes_biomarker": "biomarker", "increases_expression": "biomarker", "decreases_expression": "biomarker",
                        "improves_healthspan_in": "healthspan", "slows_aging_in": "healthspan", "extends_lifespan_in": "lifespan",
                        "shortens_lifespan_in": "lifespan", "no_lifespan_effect_in": "lifespan"}


def registry_defaults(card: HypothesisCard, raw_text: str) -> list[str]:
    """normalize_card/v10 and later (fresh calibration 2026-11-06: 4 of 44 cards stopped at admission for a field the text
    implies): an unknown endpoint is taken from the outcome claim's relation (for a registry text also promotes/suppresses:
    a health measure of people); an unknown population of a registry text is the registry's conditions, in humans; an AI-role
    span that is not verbatim in the text sets the role to "none". Returns what it filled."""
    filled = []
    registry = raw_text.startswith("A trial registered")
    out = card.outcome_claim
    if card.pico.outcome.endpoint == "unknown" and out is not None:
        ep = ENDPOINT_BY_RELATION.get(out.relation) or ("healthspan" if registry and out.relation in ("promotes", "suppresses") else None)
        if ep:
            card.pico.outcome.endpoint = ep
            filled.append(f"endpoint {ep} from relation {out.relation}")
    pop = card.pico.population
    if registry and pop.label in ("", "unknown") and not pop.taxon:
        m = re.search(r"^Conditions:\s*(.+)$", raw_text, re.M)
        pop.label, pop.taxon = (m.group(1).strip()[:120] if m else "trial participants"), "NCBITaxon:9606"
        filled.append("population from the registry conditions")
    if card.ai_role != "none" and (not card.ai_role_span or re.sub(r"\s+", " ", card.ai_role_span).strip().lower()
                                   not in re.sub(r"\s+", " ", raw_text).lower()):
        card.ai_role, card.ai_role_span = "none", ""
        filled.append("ai_role none: span not in the text")
    return filled


def _problems(value: dict, raw_text: str, card_id: str) -> tuple[Optional[HypothesisCard], list[str]]:
    value = _closed_fields(value)
    try:
        card = HypothesisCard.model_validate({**value, "id": card_id, "raw_id": card_id})
    except ValidationError as e:
        return None, [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:12]]
    set_sex_scope(card, raw_text)                       # `any` from the words "at least one sex" when the model left it out
    canonicalize(card)                                  # dose and age in one wording (L1.8)
    return mark_inherited(card), validate_card(card, raw_text)


def normalize(client, family: str, raw_text: str, card_id: str, log: Optional[list] = None,
              rounds: int = 3, version: Optional[str] = None) -> tuple[Optional[HypothesisCard], list[str]]:
    """(card or None, remaining problems). An outcome claim with relation `other` gets one re-parse with a hint
    listing the nearest vocabulary relations (spec 5); if it stays `other`, admission flags it."""
    variables = {"text": raw_text, "relations": ", ".join(typing.get_args(Relation)),
                 "hallmarks": ", ".join(typing.get_args(Hallmark)), "hint": ""}
    run = lambda v: ask(client, role="normalize_card", family=family, template=TEMPLATE[0], version=version or TEMPLATE[1],
                        variables=v, validate=lambda x: _problems(x, raw_text, card_id)[1], rounds=rounds, log=log)[0]
    value = run(variables)
    if value is None:
        return None, ["no valid JSON from the normalizer"]
    first, _ = _problems(value, raw_text, card_id)
    out = first.outcome_claim if first is not None else None
    if out is not None and out.relation == "other":
        near = nearest_relations(f"{out.note} {out.source_span} {out.object.label}")
        hint = (f'In an earlier parse the outcome claim ("{out.source_span}") got relation "other" (note: '
                f'"{out.note or "none"}"). Check whether one of these relations fits it: {", ".join(near)}. '
                f'Keep "other" only if none of them states what the text says.')
        again = run({**variables, "hint": hint})
        if again is not None and _problems(again, raw_text, card_id)[0] is not None:
            value = again
    card, problems = _problems(value, raw_text, card_id)
    if card is not None and problems:                  # drop claims whose span is not verbatim, keep the rest
        bad = {p.split(":")[0] for p in problems if "source_span" in p}
        if bad and len(bad) < len(card.claims):
            card.claims = [c for c in card.claims if c.id not in bad]
            card.edges = [e for e in card.edges if e.from_ not in bad and e.to not in bad]
            problems = validate_card(card, raw_text)
    if card is not None and int((version or TEMPLATE[1]).lstrip("v") or 0) >= 10:
        registry_defaults(card, raw_text)
    return card, problems

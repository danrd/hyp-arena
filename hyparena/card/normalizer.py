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

TEMPLATE = ("normalize_card", "v6")       # v6 adopted 2026-10-29 by the user's decision, see docs/archive/rules-method.md

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


# ---- union of two parses (method v3.9, user decision 2026-11-11) -------------------------------------------------------
# Two parses of the same text at temperature 0 still differ (H49: the first parse missed the mechanism steps the second
# wrote, both with verbatim spans). The card is the union of the parses: every claim either parse wrote with a verbatim span,
# matched by (subject, relation, object, and the measure where the object is the organism); the first parse keeps its ids and its outcome claim; a missing field of the
# experiment or the PICO is taken from the second. The agreement of the parses is kept as the card's stability.

ORGANISM_RELATIONS = ("improves_healthspan_in", "extends_lifespan_in", "shortens_lifespan_in", "slows_aging_in",
                      "no_lifespan_effect_in")


def _claim_key(c) -> tuple:
    """Subject, relation, object; the measure only where the object is the organism (there the measure is what changes;
    elsewhere it restates the object: "body composition" / "bioelectrical impedance analysis")."""
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    measure = norm(c.qualifiers.get("measure")) if c.relation in ORGANISM_RELATIONS else ""
    return (norm(c.subject.label), c.relation, norm(c.object.label), measure)


def _unknown(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip().lower() in ("", "unknown"))


def union_cards(a: HypothesisCard, b: HypothesisCard, raw_text: str) -> tuple[HypothesisCard, dict]:
    card = a.model_copy(deep=True)
    keys = {_claim_key(c): c.id for c in card.claims}
    idmap, added = {}, []
    used = {c.id for c in card.claims}
    n = max([int(m.group(1)) for c in card.claims if (m := re.fullmatch(r"c(\d+)", c.id))] or [0])
    for c in b.claims:
        k = _claim_key(c)
        if k in keys:
            idmap[c.id] = keys[k]
            continue
        n += 1
        while f"c{n}" in used:
            n += 1
        nc = c.model_copy(deep=True)
        nc.id = f"c{n}"
        used.add(nc.id)
        if nc.role == "outcome":                       # one outcome claim: the first parse's
            nc.role = "premise"
        card.claims.append(nc)
        keys[k] = nc.id
        idmap[c.id] = nc.id
        added.append(nc.id)
    have = {(e.from_, e.to, e.type) for e in card.edges}
    for e in b.edges:
        f, t = idmap.get(e.from_), idmap.get(e.to)
        if f and t and (f, t, e.type) not in have:
            card.edges.append(e.model_copy(update={"from_": f, "to": t}))
            have.add((f, t, e.type))
    filled, conflicts = [], []
    for part in ("decisive_experiment",):
        pa, pb = getattr(card, part), getattr(b, part)
        for field in type(pa).model_fields:
            va, vb = getattr(pa, field), getattr(pb, field)
            if _unknown(va) and not _unknown(vb):
                setattr(pa, field, vb)
                filled.append(f"{part}.{field}")
            elif not _unknown(va) and not _unknown(vb) and va != vb:
                conflicts.append(f"{part}.{field}: {va!r} / {vb!r}")
    pop_a, pop_b = card.pico.population, b.pico.population
    for field in type(pop_a).model_fields:
        if _unknown(getattr(pop_a, field)) and not _unknown(getattr(pop_b, field)):
            setattr(pop_a, field, getattr(pop_b, field))
            filled.append(f"pico.population.{field}")
    alt_keys = {_claim_key(x) for x in card.declared_alternatives}
    for x in b.declared_alternatives:
        if _claim_key(x) not in alt_keys:
            card.declared_alternatives.append(x.model_copy(deep=True))
            alt_keys.add(_claim_key(x))
    shared = len({_claim_key(c) for c in a.claims} & {_claim_key(c) for c in b.claims})
    total = len({_claim_key(c) for c in a.claims} | {_claim_key(c) for c in b.claims})
    stability = {"claims": [len(a.claims), len(b.claims)], "shared": shared, "jaccard": round(shared / total, 3) if total else 1.0,
                 "added_from_second": added, "filled_from_second": filled, "conflicts": conflicts}
    return card, stability


def normalize_union(client, family: str, raw_text: str, card_id: str, log: Optional[list] = None, runs: int = 2,
                    version: Optional[str] = None) -> tuple[Optional[HypothesisCard], list[str], dict]:
    """`runs` independent parses united (runs = 1: a single parse). Returns (card, problems, stability)."""
    parses = [normalize(client, family, raw_text, card_id, log=log, version=version) for _ in range(max(1, runs))]
    good = [(c, p) for c, p in parses if c is not None]
    if not good:
        return None, parses[0][1], {"parses": len(parses), "valid": 0}
    card, problems = good[0]
    stab = {"parses": len(parses), "valid": len(good)}
    for other, _ in good[1:]:
        card, s = union_cards(card, other, raw_text)
        stab.update(s)
    if len(good) > 1:
        problems = validate_card(card, raw_text)
    return card, problems, stab

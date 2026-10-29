"""Canonical wording of what a normalizer writes: dose, age at the start (also ranges), intervention names without a route word, the organism
as the object of a lifespan or healthspan claim.

The normalizer copies the wording of the text ("30 ppm food", "30 ppm", "100000 ppm in food", "4 months", "4 months of age", "4 mo"), so two texts
with the same meaning gave cards that differ as strings (L1.8, L1.9). Dose and age are written in one form after parsing; a value that does not
match a known pattern is left as it is. Applied to new normalizations only: saved cards and the frozen ITP runs are not touched."""
from __future__ import annotations

import re
from typing import Optional

AGE = re.compile(r"^\s*(?:from\s+|at\s+|starting\s+at\s+)?(\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?)\s*(months?|mos?|mo|weeks?|wks?|wk|years?|yrs?|yr|y|days?|d)\b(?:\s+(?:of\s+age|old))?\s*$", re.I)
UNIT = {"mo": "months", "mos": "months", "month": "months", "months": "months", "wk": "weeks", "wks": "weeks", "week": "weeks", "weeks": "weeks",
        "y": "years", "yr": "years", "yrs": "years", "year": "years", "years": "years", "d": "days", "day": "days", "days": "days"}
PPM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*ppm(?:\s+(?:in\s+(?:the\s+)?)?(food|diet|feed|chow|drinking\s+water|water))?\s*$", re.I)


def _num(x: str) -> str:
    """A number as written without a trailing .0; a range "5 - 9" as "5-9"."""
    parts = re.split(r"\s*[-–]\s*", x.strip())
    return "-".join(str(int(float(p))) if float(p) == int(float(p)) else str(float(p)) for p in parts)


def age(value: str) -> str:
    m = AGE.match(value or "")
    return f"{_num(m.group(1))} {UNIT[m.group(2).lower()]}" if m else value


ROUTE_WORDS = re.compile(r"^\s*(?:dietary|diet|oral|feeding(?:\s+of)?|supplementation\s+with|dietary\s+supplementation\s+with)\s+(?=\S)", re.I)
ORGANISM_RELATIONS = {"extends_lifespan_in", "shortens_lifespan_in", "no_lifespan_effect_in", "improves_healthspan_in", "slows_aging_in"}
ORGANISM = {"mouse": "mouse", "rat": "rat", "worm": "worm", "fly": "fly", "yeast": "yeast", "human": "human"}


def intervention_label(value: str) -> str:
    """The route word belongs to the regimen, not to the name: "Dietary fisetin" -> "fisetin" (the route is kept in pico.intervention.route)."""
    out = ROUTE_WORDS.sub("", value or "")
    return out if out.strip() else value


def organism_label(value: str) -> str:
    """The object of a lifespan or healthspan claim is the organism; strain and wording go to qualifiers: "genetically heterogeneous UM-HET3 mice" -> "mouse"."""
    from hyparena.card.rules import species_key
    return ORGANISM.get(species_key(value or ""), value)


def dose(value: str, route: Optional[str] = None) -> str:
    """"30 ppm", "30 ppm in food" -> "30 ppm food"; a bare ppm takes the route of the intervention (diet, water) when it is known."""
    m = PPM.match(value or "")
    if not m:
        return value
    where = (m.group(2) or "").lower()
    kind = "water" if "water" in where else "food" if where else {"diet": "food", "water": "water"}.get(route or "", "")
    return f"{_num(m.group(1))} ppm {kind}".strip()


def canonicalize(card) -> None:
    """Dose and age of the claims' qualifiers and of the PICO, the route word out of intervention names, and the organism as the object of
    lifespan and healthspan claims, in place."""
    route = next((i.route for i in card.pico.intervention if i.route in ("diet", "water")), None)
    names = {i.label: intervention_label(i.label) for i in card.pico.intervention}
    for i in card.pico.intervention:
        i.label = names[i.label]
    for c in [*card.claims, *card.declared_alternatives]:
        c.subject.label = names.get(c.subject.label, intervention_label(c.subject.label))
        if c.relation in ORGANISM_RELATIONS:
            c.object.label = organism_label(c.object.label)
        q = c.qualifiers
        if q.get("age_at_start"):
            q["age_at_start"] = age(q["age_at_start"])
        if q.get("dose"):
            q["dose"] = dose(q["dose"], route)
    if card.pico.population.age_at_start:
        card.pico.population.age_at_start = age(card.pico.population.age_at_start)
    for i in card.pico.intervention:
        if i.regimen:
            i.regimen = dose(i.regimen, i.route if i.route in ("diet", "water") else None)

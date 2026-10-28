"""Canonical wording of the qualifiers a normalizer writes: dose and age at the start.

The normalizer copies the wording of the text ("30 ppm food", "30 ppm", "100000 ppm in food", "4 months", "4 months of age", "4 mo"), so two texts
with the same meaning gave cards that differ as strings (L1.8, L1.9). Dose and age are written in one form after parsing; a value that does not
match a known pattern is left as it is. Applied to new normalizations only: saved cards and the frozen ITP runs are not touched."""
from __future__ import annotations

import re
from typing import Optional

AGE = re.compile(r"^\s*(?:from\s+|at\s+|starting\s+at\s+)?(\d+(?:\.\d+)?)\s*(months?|mos?|mo|weeks?|wks?|wk|years?|yrs?|yr|y|days?|d)\b(?:\s+(?:of\s+age|old))?\s*$", re.I)
UNIT = {"mo": "months", "mos": "months", "month": "months", "months": "months", "wk": "weeks", "wks": "weeks", "week": "weeks", "weeks": "weeks",
        "y": "years", "yr": "years", "yrs": "years", "year": "years", "years": "years", "d": "days", "day": "days", "days": "days"}
PPM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*ppm(?:\s+(?:in\s+(?:the\s+)?)?(food|diet|feed|chow|drinking\s+water|water))?\s*$", re.I)


def _num(x: str) -> str:
    return str(int(float(x))) if float(x) == int(float(x)) else str(float(x))


def age(value: str) -> str:
    m = AGE.match(value or "")
    return f"{_num(m.group(1))} {UNIT[m.group(2).lower()]}" if m else value


def dose(value: str, route: Optional[str] = None) -> str:
    """"30 ppm", "30 ppm in food" -> "30 ppm food"; a bare ppm takes the route of the intervention (diet, water) when it is known."""
    m = PPM.match(value or "")
    if not m:
        return value
    where = (m.group(2) or "").lower()
    kind = "water" if "water" in where else "food" if where else {"diet": "food", "water": "water"}.get(route or "", "")
    return f"{_num(m.group(1))} ppm {kind}".strip()


def canonicalize(card) -> None:
    """Dose and age of the claims' qualifiers and of the PICO, in place."""
    route = next((i.route for i in card.pico.intervention if i.route in ("diet", "water")), None)
    for c in [*card.claims, *card.declared_alternatives]:
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

"""`late_start` (card spec 8a, agreed 2026-10-21): age at the start of the intervention as a fraction of the
species' median lifespan, capped at 1. An exact age ("600 days", "20 months", "65 years") gives a number; a
verbal age ("middle age", "older adults") an interval from a per-species table, drawn uniformly by the
aggregation; an unknown age, or a species without a median in the table, stays unknown (drawn over [0, 1]).
Tables: configs/lifespan_medians.yaml (values with sources)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

import yaml

from hyparena.card.models import UNKNOWN, HypothesisCard
from hyparena.card.rules import species_key, strain_key

TABLE = Path(__file__).resolve().parents[2] / "configs" / "lifespan_medians.yaml"
DAYS = {"day": 1.0, "week": 7.0, "wk": 7.0, "month": 30.44, "mo": 30.44, "year": 365.25, "yr": 365.25}
Value = Union[float, tuple[float, float], None]


@lru_cache(maxsize=4)
def load(path: Path = TABLE) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {"medians": data.get("medians") or [], "verbal_ages": data.get("verbal_ages") or {}}


def age_days(text: str) -> Optional[float]:
    """An exact age in days: "600 days", "20 months", "20-month-old", "65 years", "12 weeks"; None otherwise
    (a range such as "18-20 months" gives its middle)."""
    m = re.search(r"(\d+(?:\.\d+)?)(?:\s*(?:-|–|to)\s*(\d+(?:\.\d+)?))?\s*-?\s*(days?|weeks?|wks?|months?|mo|years?|yrs?)\b",
                  (text or "").lower())
    if not m:
        return None
    a = float(m.group(1))
    b = float(m.group(2)) if m.group(2) else a
    unit = next(u for u in DAYS if m.group(3).startswith(u))
    return (a + b) / 2 * DAYS[unit]


def median_days(species: str, strain: str = "", sex: str = "", table: Optional[dict] = None) -> Optional[float]:
    """The median lifespan for a species, most specific entry first: species + strain + sex, + strain, + sex,
    species alone."""
    rows = [r for r in (table or load())["medians"] if species_key(r.get("species", "")) == species]
    st, sx = strain_key(strain or ""), (sex or "").lower()
    for need_strain, need_sex in ((True, True), (True, False), (False, True), (False, False)):
        for r in rows:
            if need_strain and (not st or strain_key(r.get("strain", "")) != st):
                continue
            if not need_strain and r.get("strain"):
                continue
            if need_sex and (sx not in ("male", "female") or (r.get("sex") or "").lower() != sx):
                continue
            if not need_sex and r.get("sex"):
                continue
            return float(r["median_days"])
    return None


def verbal_interval(species: str, text: str, table: Optional[dict] = None) -> Optional[tuple[float, float]]:
    """The interval of the fraction for a verbal age, from the species' table."""
    low = re.sub(r"[_\s]+", " ", (text or "").lower()).strip()
    for row in ((table or load())["verbal_ages"].get(species) or []):
        if any(t.lower() in low for t in row.get("terms", [])):
            lo, hi = row["fraction"]
            return float(lo), float(hi)
    return None


def late_start(card: HypothesisCard, table: Optional[dict] = None) -> Value:
    """A number, an interval (lo, hi) or None (unknown) for the card's population."""
    pop = card.pico.population
    species = species_key(pop.label) or species_key(pop.taxon or "")
    age = pop.age_at_start
    if not species or not age or age.strip().lower() in (UNKNOWN, "", "n/a"):
        return None
    days = age_days(age)
    if days is not None:
        med = median_days(species, pop.strain, pop.sex, table)
        return min(1.0, days / med) if med else None
    return verbal_interval(species, age, table)

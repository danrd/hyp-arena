"""`late_start` (card spec 8a; tables and lookup rule: Data_Sources 19): the age at the start of the intervention
as a fraction of the median lifespan of controls, capped at 1. An exact age ("600 days", "20 months", "65 years")
or a verbal age ("middle age", "older adults": an age interval per species) is divided by the medians that fit
the card: species + strain + sex; strain unknown → all strains of the species; sex unknown → the "both" row if
there is one, else all sexes. With medians [m_lo, m_hi] and ages [a_lo, a_hi] the fraction is
[a_lo / m_hi, min(1, a_hi / m_lo)]: a number when both are points, else an interval that the aggregation draws
uniformly. A species, strain or sex not in the table, assay conditions the card states that differ from the row's
(worms: 20 °C with FUdR; flies: 25 °C), or an age it cannot read, stay unknown (drawn over [0, 1]).
Tables: configs/lifespan_medians.yaml."""
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
UNIT_DAYS = {"days": 1.0, "months": 30.44, "years": 365.25}
LOW_INCOME = ("low-income", "low income", "middle-income", "middle income", "lmic", "developing countr")
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


def _median_days(row: dict) -> tuple[float, float]:
    if "median_years" in row:
        v, k = row["median_years"], UNIT_DAYS["years"]
    else:
        v, k = row["median_days"], 1.0
    lo, hi = (v if isinstance(v, (list, tuple)) else (v, v))
    return float(lo) * k, float(hi) * k


def _known(v: Optional[str]) -> bool:
    return bool(v) and v.strip().lower() not in (UNKNOWN, "", "n/a", "none")


TEMPERATURE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:°\s*c\b|º\s*c\b|degrees?\s*c(?:elsius)?\b)")
NO_FUDR = re.compile(r"(?:without|no|absence of|free of|lacking)\s+(?:fudr|floxuridine)|(?:fudr|floxuridine)[- ]free")
FUDR = re.compile(r"\b(?:fudr|floxuridine)\b")


def stated_conditions(card: HypothesisCard) -> dict:
    """Assay conditions the card states anywhere in its text fields: temperature (°C), FUdR yes/no."""
    p = card.pico
    text = " ".join([card.claim_plain, p.population.label, p.population.strain, p.outcome.metric,
                     *(f"{i.label} {i.regimen}" for i in p.intervention),
                     *(f"{c.source_span} {' '.join(c.qualifiers.values())}" for c in card.claims)]).lower()
    out = {}
    m = TEMPERATURE.search(text)
    if m:
        out["temperature_c"] = float(m.group(1))
    if NO_FUDR.search(text):
        out["fudr"] = False
    elif FUDR.search(text):
        out["fudr"] = True
    return out


def _conditions_fit(row: dict, stated: dict) -> bool:
    """A row applies unless the card states a condition that differs from the row's."""
    return all(k not in stated or stated[k] == v for k, v in (row.get("conditions") or {}).items())


def median_interval(species: str, strain: str = "", sex: str = "", population: str = "",
                    table: Optional[dict] = None, conditions: Optional[dict] = None) -> Optional[tuple[float, float]]:
    """[m_lo, m_hi] in days for the card's species, strain, sex and stated conditions (Data_Sources 19), or None."""
    rows = [r for r in (table or load())["medians"] if species_key(r.get("species", "")) == species
            and _conditions_fit(r, conditions or {})]
    if species == "human" and rows:                    # setting: high-income by default, world for LMIC populations
        setting = "world" if any(w in (population or "").lower() for w in LOW_INCOME) else "high-income countries"
        rows = [r for r in rows if r.get("strain", "") == setting]
    elif _known(strain):
        want = strain_key(strain)
        rows = [r for r in rows if want and (want in strain_key(r.get("strain", "")) or strain_key(r.get("strain", "")) in want)]
    sx = (sex or "").strip().lower()
    if sx in ("male", "female", "hermaphrodite"):
        rows = [r for r in rows if r.get("sex") == sx]
    elif any(r.get("sex") == "both" for r in rows):
        rows = [r for r in rows if r.get("sex") == "both"]
    if not rows:
        return None
    meds = [_median_days(r) for r in rows]
    return min(m[0] for m in meds), max(m[1] for m in meds)


def verbal_age_days(species: str, text: str, table: Optional[dict] = None) -> Optional[tuple[float, Optional[float]]]:
    """The age interval in days for a verbal age (upper bound None = open), longest matching term first."""
    spec = (table or load())["verbal_ages"].get(species)
    if not spec:
        return None
    low = re.sub(r"[_\s]+", " ", (text or "").lower()).strip()
    k = UNIT_DAYS[spec.get("unit", "days")]
    terms = sorted(((t.lower(), row) for row in spec.get("rows", []) for t in row.get("terms", [])), key=lambda x: -len(x[0]))
    for term, row in terms:
        if re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", low):
            lo, hi = row["age"]
            return float(lo) * k, (float(hi) * k if hi is not None else None)
    return None


def late_start(card: HypothesisCard, table: Optional[dict] = None) -> Value:
    """A number, an interval (lo, hi) or None (unknown) for the card's population."""
    pop = card.pico.population
    species = species_key(pop.label) or species_key(pop.taxon or "")
    age = pop.age_at_start
    if not species or not _known(age):
        return None
    med = median_interval(species, pop.strain, pop.sex, pop.label, table, stated_conditions(card))
    if med is None:
        return None
    days = age_days(age)
    ages = (days, days) if days is not None else verbal_age_days(species, age, table)
    if ages is None:
        return None
    lo = min(1.0, ages[0] / med[1])
    hi = 1.0 if ages[1] is None else min(1.0, ages[1] / med[0])
    return round(lo, 4) if abs(hi - lo) < 1e-9 else (round(lo, 4), round(hi, 4))

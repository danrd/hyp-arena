"""Ordinal scales of method v3 and their weights (docs/spec/method-v3.md, section 3).

Rule (user decision 2026-11-03): a scale with k ordered levels gives level i (1-based, lowest first) the weight i/k. A departure
from equal steps is made only when calibration shows that equal steps break something, and is recorded in the spec.
"""
from __future__ import annotations

from typing import Optional

SCALES: dict[str, tuple[str, ...]] = {
    "design_human": ("cells", "animal", "observational", "review", "non_randomised", "meta_analysis", "rct"),
    "design_animal": ("cells", "review", "animal"),
    "precision": ("lt30", "30_99", "100_299", "ge300"),          # unknown n -> lowest band
    "effect": ("none", "small", "medium", "large"),              # "unclear" -> 0.5, the middle of the scale
    "comparison": ("none", "within_group", "between_groups"),
    "context": ("class", "adjacent", "exact"),
    "link": ("refuted", "contested", "unverified", "weak", "moderate", "strong"),
    # v3.1 (2026-11-05): data in conflict ranks above no data (method-v3.md section 12, point 3)
    "link_v31": ("refuted", "unverified", "contested", "weak", "moderate", "strong"),
    # v3.1: support of an alternative above the unverified level, three equal steps (section 12, point 6b)
    "alt_support_v31": ("weak", "moderate", "strong"),
    "scope": ("local", "organ", "hallmark"),
    "discrimination": ("unchanged", "weakened", "eliminated"),   # weight (i-1)/(k-1): unchanged 0, weakened 0.5, eliminated 1
}
ZERO_BASED = {"discrimination"}          # a scale whose lowest level means "nothing": 0 .. 1 instead of 1/k .. 1


def weight(scale: str, level: str) -> float:
    levels = SCALES[scale]
    if scale == "effect" and level == "unclear":
        return 0.5
    if level not in levels:
        raise ValueError(f"{scale}: unknown level {level!r} (levels: {', '.join(levels)})")
    i = levels.index(level)
    if scale in ZERO_BASED:
        return i / (len(levels) - 1)
    return (i + 1) / len(levels)


def precision_band(n: Optional[int]) -> str:
    if n is None or n < 30:
        return "lt30"
    if n < 100:
        return "30_99"
    if n < 300:
        return "100_299"
    return "ge300"


def design_weight(design: str, human_claim: bool) -> float:
    """Design weight; designs outside the scale (other, unknown) take the lowest level of it."""
    scale = "design_human" if human_claim else "design_animal"
    levels = SCALES[scale]
    if design == "meta_analysis" and not human_claim:
        design = "review"
    if design in ("non_randomised", "observational", "rct") and not human_claim:
        design = "animal"                                         # a primary study in animals
    return weight(scale, design if design in levels else levels[0])

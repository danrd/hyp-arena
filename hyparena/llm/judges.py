"""Judge pool and the independence rule: judges must not share a family with the text's writer."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, Literal

from hyparena.state import Hypothesis

LineageMode = Literal["writer", "lineage"]

#: Provenance families that carry no exclusion information (nothing can be ruled out).
UNKNOWN_FAMILIES = {"unknown", "human"}


@dataclass(frozen=True)
class JudgeSpec:
    family: str
    model_version: str


def excluded_families(h: Hypothesis, hypotheses: dict[str, Hypothesis], mode: LineageMode) -> set[str]:
    """Families a judge may not belong to for `h`. `writer`: only who wrote this text.
    `lineage`: the writer and every ancestor."""
    if mode == "writer":
        families = {h.provenance.family}
    else:
        families, stack, seen = set(), [h], set()
        while stack:
            cur = stack.pop()
            if cur.id in seen:
                continue
            seen.add(cur.id)
            families.add(cur.provenance.family)
            stack.extend(hypotheses[p] for p in cur.parents if p in hypotheses)
    return families - UNKNOWN_FAMILIES


def eligible_judges(pool: Iterable[JudgeSpec], a: Hypothesis, b: Hypothesis,
                    hypotheses: dict[str, Hypothesis], mode: LineageMode,
                    exclude: Iterable[str] = ()) -> list[JudgeSpec]:
    banned = (excluded_families(a, hypotheses, mode) | excluded_families(b, hypotheses, mode)
              | set(exclude))
    return [j for j in pool if j.family not in banned]


def pick_judges(pool: Iterable[JudgeSpec], a: Hypothesis, b: Hypothesis,
                hypotheses: dict[str, Hypothesis], mode: LineageMode, k: int,
                rng: random.Random, exclude: Iterable[str] = ()) -> list[JudgeSpec]:
    """Up to `k` eligible judges, one per family (the pool holds one model per family).
    Fewer than `k` are returned when fewer are eligible; the caller decides what that means."""
    eligible = eligible_judges(pool, a, b, hypotheses, mode, exclude)
    return rng.sample(eligible, min(k, len(eligible)))

"""Ablation ladder from the Co-Scientist baseline (L0) to our full method (L4), one change per step.
L0ts is the second baseline: the 2026 version of Co-Scientist (TrueSkill + UCB) instead of Elo.

Every step runs the same upstream stages (normalization, retrieval, reviews); only the ranking differs.
See docs/comparison.md."""
from __future__ import annotations

from dataclasses import dataclass, field

BASELINE = dict(rating="elo", pairing="coscientist", judge_view="coscientist", lineage_mode="none",
                judges_per_match=1, extra_judges=0)


@dataclass(frozen=True)
class Step:
    name: str
    description: str
    criteria: str                       # file in configs/
    single_family: bool                 # one model family for every role (as Co-Scientist)
    cfg: dict = field(default_factory=dict)


LADDER = {
    "L0": Step("L0", "Co-Scientist baseline: one family, holistic verdict on text and reviews, Elo, its pairing",
               "criteria-coscientist.yaml", True, dict(BASELINE)),
    "L0ts": Step("L0ts", "Co-Scientist 2026 baseline (arXiv 2608.26701): as L0 with TrueSkill ratings and UCB "
                 "selection of contenders", "criteria-coscientist.yaml", True,
                 {**BASELINE, "rating": "trueskill", "pairing": "ucb"}),
    "L1": Step("L1", "+ verdicts per criterion", "criteria.yaml", True, dict(BASELINE)),
    "L2": Step("L2", "+ Bradley-Terry with intervals and elimination pairing", "criteria.yaml", True,
               {**BASELINE, "rating": "bt", "pairing": "bt"}),
    "L3": Step("L3", "+ judges see the card and the retrieved evidence", "criteria.yaml", True,
               {**BASELINE, "rating": "bt", "pairing": "bt", "judge_view": "full"}),
    "L4": Step("L4", "full method: + ensemble of independent families (judges never from the writer's family)",
               "criteria.yaml", False, {}),
}

MODES = {"coscientist": "L0", "coscientist-2026": "L0ts", "full": "L4"}

"""The d of the proposed alternatives judged from the registry text (judge_alternatives/v2; user decision 2026-11-08,
specs/informativeness-check-2026-11-08.yaml): it replaces the on_positive / on_negative that propose_alternatives/v1 set
from the compressed card. Applied where saved runs are read (scripts.v34_check.parts, scripts.ablation.units, the
report builder). A unit without a judged d keeps its own."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from hyparena.card.models import HypothesisCard

KG = Path(os.environ.get("KG_DIR", Path(__file__).resolve().parents[3] / "longevity-kg"))
FILES = (KG / "hypothesis_sources" / "calibration" / "judge_alternatives_v2.json",
         KG / "hypothesis_sources" / "prospective" / "judge_alternatives_v2.json")
ENABLED = os.environ.get("JUDGED_D", "1") != "0"     # JUDGED_D=0 reproduces the runs before 2026-11-08


@lru_cache(maxsize=1)
def judged() -> dict:
    out = {}
    for f in FILES:
        if f.exists():
            for h, v in json.loads(f.read_text()).items():
                out[h] = v.get("d") or {}
    return out


def apply(unit_id: str, card: HypothesisCard) -> HypothesisCard:
    d = judged().get(unit_id) if ENABLED else None
    if not d:
        return card
    alts = [a.model_copy(update={"on_positive": d[a.id]["d_positive"], "on_negative": d[a.id]["d_negative"]})
            if a.id in d else a for a in card.proposed_alternatives]
    return card.model_copy(update={"proposed_alternatives": alts})

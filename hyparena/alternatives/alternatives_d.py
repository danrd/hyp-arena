"""The d of the proposed alternatives judged from the registry text (judge_alternatives/v2; user decision 2026-11-08,
specs/alternatives/informativeness-check-2026-11-08.yaml): it replaces the on_positive / on_negative that propose_alternatives/v1 set
from the compressed card. Applied where saved runs are read (scripts.common.v34_check.parts, scripts.common.ablation.units, the
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


# the runs whose proposed alternatives the judge saw (judge_alternatives/v2 keeps only the alternative ids)
JUDGED_RUNS = [KG / "hypothesis_sources" / "calibration" / f"run_{s}_v10.json" for s in range(1, 6)] + \
              [KG / "hypothesis_sources" / "prospective" / "run_60.json"]


def _key(a) -> tuple:
    get = (lambda o, k: o.get(k)) if isinstance(a, dict) else (lambda o, k: getattr(o, k))
    lab = lambda o: (o.get("label") if isinstance(o, dict) else o.label) or ""
    return (lab(get(a, "subject")).strip().lower(), get(a, "relation"), lab(get(a, "object")).strip().lower())


@lru_cache(maxsize=1)
def judged_alternatives() -> dict:
    """{unit: {alternative id: (subject, relation, object)}} of the alternatives the judge saw."""
    out = {}
    for f in JUDGED_RUNS:
        if f.exists():
            for h, r in json.loads(f.read_text()).items():
                it = (r.get("items") or [{}])[0]
                out[h] = {a["id"]: _key(a) for a in ((it.get("card") or {}).get("proposed_alternatives") or [])}
    return out


def apply(unit_id: str, card: HypothesisCard) -> HypothesisCard:
    """The judged d for each proposed alternative that is the one the judge saw (same id, subject, relation and object);
    a card with other alternatives under the same ids (a newer normaliser or run, 2026-11-15) keeps its own."""
    d = judged().get(unit_id) if ENABLED else None
    if not d:
        return card
    seen = judged_alternatives().get(unit_id, {})
    alts = [a.model_copy(update={"on_positive": d[a.id]["d_positive"], "on_negative": d[a.id]["d_negative"]})
            if a.id in d and seen.get(a.id) == _key(a) else a for a in card.proposed_alternatives]
    return card.model_copy(update={"proposed_alternatives": alts})

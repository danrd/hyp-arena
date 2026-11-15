"""The gate fixes of specs/scoring/gate-fixes-2026-11-15.yaml as variants against the references; free, no model call.

    python -m scripts.scoring.gate_variants          # -> longevity-kg reviews/argon-2026-11-15/gate_variants.json

References: R3 (calibration trial outcomes, 74 trials, saved v10 runs) and the AUC of the evidence balance on the 30 trials of
pack 18 with reader v17 + cross-link (run_*_n15x) and reader v16 (run_*_n14x); per reference, the trials the gate filters.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

from hyparena.scoring import rules_v3 as r3
from scripts.scoring.weight_variants import OUT

ALL = ("exact", "class", "adjacent")
VARIANTS = {
    "current": {},
    "G1 named outcome": {"named": True},
    "G2 counterweight in any context": {"contexts": ALL},
    "G1 and G2": {"named": True, "contexts": ALL},
}


@contextmanager
def variant(v: dict):
    saved = (r3.GATE_OUTCOME_NAMED, r3.GATE_SUPPORT_CONTEXTS)
    try:
        r3.GATE_OUTCOME_NAMED = v.get("named", False)
        r3.GATE_SUPPORT_CONTEXTS = v.get("contexts", ("exact",))
        yield
    finally:
        r3.GATE_OUTCOME_NAMED, r3.GATE_SUPPORT_CONTEXTS = saved


def _filtered_r3() -> dict:
    from hyparena.scoring import rules_v32 as r32
    from scripts.common.ablation import units
    out = {"positive": [], "negative": []}
    for u in units():
        if r32.evaluate(u["card"], u["cvs"], u["alts"], v36=True).gate != "pass":
            out["positive" if u["label"] == 1 else "negative"].append(u.get("id", "?"))
    return out


def _filtered_30(tag: str) -> dict:
    from hyparena.alternatives import alternatives_d
    from hyparena.card.models import ClaimVerification, HypothesisCard
    from hyparena.scoring import rules_v32 as r32
    from scripts.common.v34_check import CAL
    from scripts.reading.reader_replay import UNITS
    ids = set(UNITS.read_text().split())
    out = {"positive": [], "negative": []}
    for s in (1, 2, 3, 4, 5):
        f = CAL / f"run_{s}_{tag}.json"
        if not f.exists():
            continue
        us = {u["id"]: u for u in json.loads((CAL / f"units_{s}.json").read_text())}
        for h, r in json.loads(f.read_text()).items():
            it = r["items"][0]
            if h not in ids or us.get(h, {}).get("label") not in (0, 1) or "v3" not in it:
                continue
            card = alternatives_d.apply(h, HypothesisCard.model_validate(it["card"]))
            cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
            alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
            if r32.evaluate(card, cvs, alts, v36=True).gate != "pass":
                out["positive" if us[h]["label"] == 1 else "negative"].append(h)
    return out


def main() -> dict:
    from hyparena.tools import compounds as cp
    from scripts.reading.reader_replay import balance_auc
    from scripts.scoring.empty_slots import r3_auc
    r3.established_by_approval = lambda claim, card: False      # ChEMBL is not reachable here; the same in every variant
    cp._get = lambda url: None
    out = {}
    for name, v in VARIANTS.items():
        with variant(v):
            out[name] = {"R3": r3_auc(), "auc30_v17": balance_auc("n15x")["auc"], "auc30_v16": balance_auc("n14x")["auc"],
                         "filtered": {"R3": _filtered_r3(), "v17": _filtered_30("n15x"), "v16": _filtered_30("n14x")}}
        print(name, {k: x for k, x in out[name].items() if k != "filtered"},
              {k: (len(x["positive"]), len(x["negative"])) for k, x in out[name]["filtered"].items()}, flush=True)
    base = out["current"]
    for name, r in out.items():
        r["worse_by_more_than_0.03"] = [k for k in ("R3", "auc30_v17", "auc30_v16") if base[k] - r[k] > 0.03]
        lifted = {s: sum(len(base["filtered"][ref][s]) - len(r["filtered"][ref][s]) for ref in base["filtered"]) for s in ("positive", "negative")}
        r["gate_lifted"] = lifted
        r["passes"] = not r["worse_by_more_than_0.03"] and lifted["negative"] <= lifted["positive"]
    (OUT / "gate_variants.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    main()

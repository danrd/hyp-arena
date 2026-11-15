"""The values Argon pack 24 suggests for the record weight (specs/scoring/weight-sources-2026-11-15.yaml), each as a variant
against the method's references; free, no model call.

    python -m scripts.scoring.weight_variants            # -> longevity-kg reviews/argon-2026-11-15/weight_variants.json

References: R2 (a later RCT or meta-analysis of the same link, scored from the earlier records: AUC), R3 (calibration trial
outcomes, 74 trials, saved v10 runs: AUC of the evidence balance), pack 23 (concordance of the record order with the outside
reader), and the AUC of the evidence balance on the 30 trials of pack 18 with the working reader (run_*_n15x.json) and with
reader v16 (run_*_n14x.json). A variant enters through the manual only when none of them gets worse by more than 0.03.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from contextlib import contextmanager

from hyparena.reading import review_kind as rk
from hyparena.scoring import rules_v32 as r32
from hyparena.scoring import v3_levels as lv
from scripts.common.v34_check import CAL

OUT = CAL.parents[1] / "reviews" / "argon-2026-11-15"

VARIANTS = {
    "current": {},
    "F1 meta-analysis not stated 0.75": {"not_reported": 0.75},
    "F1 meta-analysis not stated 0.5": {"not_reported": 0.5},
    "F2 narrative review on the preclinical scale 1/3": {"preclinical_review": 1 / 3},
    "F5 any stated effect 1": {"effect_rule": "stated"},
    "F7 same class 0.75": {"class_weight": 0.75},
    "F7 same class 0.5": {"class_weight": 0.5},
    "F8 further records of one trial 0": {"fold_rest": 0.0},
    "F9 slope 1.6": {"slope": 1.6},
}


@contextmanager
def variant(v: dict):
    saved = (rk.NOT_REPORTED, r32.EFFECT_RULE, r32.CLASS_WEIGHT, r32.FOLD_REST, r32.LOGLR_LAMBDA, lv.weight)
    try:
        rk.NOT_REPORTED = v.get("not_reported", rk.NOT_REPORTED)
        r32.EFFECT_RULE = v.get("effect_rule", r32.EFFECT_RULE)
        r32.CLASS_WEIGHT = v.get("class_weight", r32.CLASS_WEIGHT)
        r32.FOLD_REST = v.get("fold_rest", r32.FOLD_REST)
        r32.LOGLR_LAMBDA = v.get("slope", r32.LOGLR_LAMBDA)
        if "preclinical_review" in v:
            base = saved[5]
            lv.weight = lambda scale, level, _b=base, _x=v["preclinical_review"]: _x if (scale == "design_animal" and level == "review") else _b(scale, level)
        yield
    finally:
        rk.NOT_REPORTED, r32.EFFECT_RULE, r32.CLASS_WEIGHT, r32.FOLD_REST, r32.LOGLR_LAMBDA, lv.weight = saved


def r2_refs():
    from scripts.scoring import record_weight_check as rw
    rows = rw.with_years(rw.pool())
    return rw.build_refs(rows)["R2"]


def r2_auc(refs) -> float | None:
    from scripts.scoring.record_weight_check import auc

    def score(u):
        side = {"for": defaultdict(list), "against": defaultdict(list)}
        for r in u["records"]:
            side[r["side"]][r["group"]].append(r32.record_weight_v36(r["rec"], r["claim_obj"], r["side"] == "against"))
        F, A = (sum(max(ws) + r32.FOLD_REST * (sum(ws) - max(ws)) for ws in side[k].values() if ws) for k in ("for", "against"))
        return 1 / (1 + math.exp(-r32.LOGLR_LAMBDA * (F - A)))
    return auc(refs, score)


def pack23(v: dict) -> float:
    """Concordance of the record order with Argon's, the weights of the key changed by the variant's factor."""
    D = OUT
    kd = json.loads((D / "pack_23_key.json").read_text())
    recs = kd["records"]
    ans, task = {}, {}
    for i in (1, 2, 3):
        ans.update({p["id"]: p for p in json.loads((D / f"pack_23_{i}_answer.json").read_text())["pairs"]})
        task.update({p["id"]: p for p in json.loads((D / f"pack_23_{i}_task.json").read_text())["pairs"]})

    def w(rid, factors):
        r, f = recs[rid], dict(factors)
        if r["design"] == "meta_analysis" and not r.get("certainty"):
            f["design"] = f["design"] / 0.75 * v.get("not_reported", 1.0)      # the key was built at 0.75
        if "preclinical_review" in v and abs(f["design"] - 2 / 3) < 1e-6 and r["design"] == "review":
            f["design"] = v["preclinical_review"]
        if v.get("effect_rule") == "stated" and r["side"] == "for":
            f["effect"] = 1.0 if (r.get("effect_reported") or "").strip() else 0.5
        if r.get("context") == "class":
            f["context"] = v.get("class_weight", 1.0)
        return math.prod(f.values())
    ok = []
    for p in kd["pairs"]:
        if p["swapped"]:
            continue
        t = task[p["id"]]
        wa, wb = w(t["A"], p["factors"][0]), w(t["B"], p["factors"][1])
        d = math.log(wa / wb) if wa > 0 and wb > 0 else 0
        o = 0 if abs(d) < 0.1 else (1 if d > 0 else -1)
        a = {"A": 1, "B": -1, "equal": 0}[ans[p["id"]]["stronger"]]
        if a and o:
            ok.append(a == o)
    return round(sum(ok) / len(ok), 3)


def main() -> dict:
    from hyparena.scoring import rules_v3 as r3
    from hyparena.tools import compounds as cp
    from scripts.reading.reader_replay import balance_auc
    from scripts.scoring.empty_slots import r3_auc
    r3.established_by_approval = lambda claim, card: False      # ChEMBL is not reachable here; the same in every variant
    cp._get = lambda url: None
    refs = r2_refs()
    out = {}
    for name, v in VARIANTS.items():
        with variant(v):
            out[name] = {"R2": r2_auc(refs), "R3": r3_auc(), "pack23": pack23(v),
                         "auc30_v17": balance_auc("n15x")["auc"], "auc30_v16": balance_auc("n14x")["auc"]}
        print(name, out[name], flush=True)
    base = out["current"]
    for name, r in out.items():
        r["worse_by_more_than_0.03"] = [k for k in base if isinstance(base[k], float) and r[k] is not None and base[k] - r[k] > 0.03]
    (OUT / "weight_variants.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    main()

"""A link supported only by small positive studies (specs/scoring/small-positives-2026-11-16.yaml): the variants against the
references, free, no model call.

    python -m scripts.scoring.small_positives      # -> calibration/small_positives.json

The working rules are not changed: the variant wraps rules_v32.side_weight for the time of the computation.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from contextlib import contextmanager

from hyparena.scoring import rules_v32 as r32

HUMAN_PRIMARY = {"rct", "non_randomised", "observational"}
VARIANTS = {"current": None, "SP100": (100, True), "SP50": (50, True), "SP100_any": (100, False)}
FACTOR = 0.5


def only_small(recs, line: int, human_only: bool) -> bool:
    """At least two independent groups for, every one small (n under the line or unknown), none a meta-analysis, none large;
    human_only: every group a human primary study."""
    if not recs:
        return False
    if any(r.design == "meta_analysis" or (r.n_total or 0) >= line for r in recs):
        return False
    if human_only and any(r.design not in HUMAN_PRIMARY for r in recs):
        return False
    return len({r32.group_key(r) for r in recs}) >= 2


@contextmanager
def variant(v):
    orig = r32.side_weight
    if v is None:
        yield
        return

    def side_weight(recs, claim, against, fold, v34=False):
        w = orig(recs, claim, against, fold, v34)
        return w * FACTOR if (not against and only_small(recs, *v)) else w
    r32.side_weight = side_weight
    try:
        yield
    finally:
        r32.side_weight = orig


def _r3(units) -> float:
    from scripts.common.ablation import auc_of
    vals = []
    for u in units:
        e = r32.evaluate(u["card"], u["cvs"], u["alts"], v36=True)
        vals.append((-1.0 if e.gate != "pass" else e.chain_state, u["label"]))
    return auc_of(vals)


def _score(u, v) -> float:
    side = {"for": defaultdict(list), "against": defaultdict(list)}
    recs_for = []
    for r in u["records"]:
        side[r["side"]][r["group"]].append(r32.record_weight_v36(r["rec"], r["claim_obj"], r["side"] == "against"))
        if r["side"] == "for":
            recs_for.append(r["rec"])
    F, A = (sum(max(ws) + r32.FOLD_REST * (sum(ws) - max(ws)) for ws in side[k].values() if ws) for k in ("for", "against"))
    if v is not None and only_small(recs_for, *v):
        F *= FACTOR
    return 1 / (1 + math.exp(-r32.LOGLR_LAMBDA * (F - A)))


def _r2(targets, v, pairs: str = "all"):
    xs = [(_score(u, v), u["label"], u["link"], u["design"]) for u in targets]
    if pairs == "meta":
        xs = [x for x in xs if x[3] == "meta_analysis"]
    P, N = [x for x in xs if x[1] == 1], [x for x in xs if x[1] == 0]
    w = m = 0.0
    for s1, _, k1, _ in P:
        for s0, _, k0, _ in N:
            if pairs == "between" and k1 == k0:
                continue
            m += 1
            w += (s1 > s0) + 0.5 * (s1 == s0)
    return round(w / m, 3) if m else None


def main() -> dict:
    import importlib
    import os
    from scripts.whole_system import calibration_r2_diag as d
    cur_targets = list(d._targets(d._rows("_cur")).values())
    os.environ["CAL_RUN_TAG"] = "_cur"
    from scripts.common import ablation
    importlib.reload(ablation)
    cur_units = ablation.units()
    os.environ["CAL_RUN_TAG"] = "_v10"
    importlib.reload(ablation)
    saved_units = ablation.units()
    out = {}
    for name, v in VARIANTS.items():
        with variant(v):
            out[name] = {"R3": _r3(cur_units), "R2_pooled": _r2(cur_targets, v), "R2_between": _r2(cur_targets, v, "between"),
                         "R2_meta": _r2(cur_targets, v, "meta"), "R3_saved": _r3(saved_units)}
        touched = sum(only_small([r["rec"] for r in u["records"] if r["side"] == "for"], *v) for u in cur_targets) if v else 0
        out[name]["R2_targets_touched"] = touched
        print(name, out[name], flush=True)
    base = out["current"]
    for name, r in out.items():
        r["worse_by_more_than_0.03"] = [k for k in ("R3", "R2_pooled", "R2_between", "R2_meta", "R3_saved")
                                        if base[k] is not None and r[k] is not None and base[k] - r[k] > 0.03]
        r["better_by_more_than_0.03"] = [k for k in ("R3", "R2_between")
                                         if base[k] is not None and r[k] is not None and r[k] - base[k] > 0.03]
    (ablation.CAL / "small_positives.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    main()

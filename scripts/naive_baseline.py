"""L3.9: our rank against the naive "approved first" order (path_to_human only) on the ITP backtest, paired over compounds.

    python -m scripts.naive_baseline --labels data/backtest/itp_2010-12-31_labels.json \\
        --runs runs/stage5/itp2010_dev.abp.json runs/stage5/itp2010_test.abp.json

The criterion is fixed in specs/validation-criteria.yaml (L3.9): paired difference of the tie-aware AUC (our rank minus the naive order)
on the same compounds, 95% bootstrap interval resampling compounds (10 000 draws). Pass: the interval is above 0. Fail: the point
difference is not above 0. Otherwise: not proven. Known results are left out of both orders; hypotheses filtered by the gate sit at the bottom
of both. Naive order: path_to_human level 0 first, higher levels later, unknown after the last level (ties share the place, count 0.5).
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from hyparena.backtest import tied_auc, tied_scores

MIN_SCORED, MIN_POSITIVES = 30, 8


def naive_scores(res: dict, ids: set[str]) -> dict[str, tuple[float, float]]:
    """(score, 0) per ranked or filtered hypothesis: minus the path_to_human level; unknown below the highest level seen; filtered lowest."""
    ids_all = res["meta"].get("ids") or [f"imp{i:03d}" for i in range(1, len(res["items"]) + 1)]
    levels = [int(x["indicators"]["path_to_human"]) for x in res["items"]
              if x["outcome"] == "ranked" and (x.get("indicators") or {}).get("path_to_human") not in (None, "")]
    top = max(levels) if levels else 0
    out = {}
    for pid, x in zip(ids_all, res["items"]):
        if pid not in ids:
            continue
        if x["outcome"] == "ranked":
            v = (x.get("indicators") or {}).get("path_to_human")
            out[pid] = (-float(int(v)) if v not in (None, "") else -(top + 1.0), 0.0)
        elif x["outcome"] == "filtered":
            out[pid] = (-(top + 2.0), 0.0)
    return out


def compound_units(labels: dict, ours: dict, naive: dict) -> list[dict]:
    by = defaultdict(list)
    for pid in ours:
        by[labels[pid]["compound"]].append(pid)
    units = []
    for comp, pids in by.items():
        o = (sum(ours[p][0] for p in pids) / len(pids), math.sqrt(sum(ours[p][1] ** 2 for p in pids)) / len(pids))
        n = (sum(naive[p][0] for p in pids) / len(pids), 0.0)
        units.append({"compound": comp, "ours": o, "naive": n, "label": max(labels[p]["label"] for p in pids)})
    return units


def paired(units: list[dict], K: int = 10000, draws: int = 10000, seed: int = 0) -> dict:
    def aucs(us):
        pos, neg = [u for u in us if u["label"] == 1], [u for u in us if u["label"] == 0]
        if not pos or not neg:
            return None
        return (tied_auc([u["ours"] for u in pos], [u["ours"] for u in neg], K),
                tied_auc([u["naive"] for u in pos], [u["naive"] for u in neg], K))
    base = aucs(units)
    n_pos = sum(u["label"] == 1 for u in units)
    out = {"n_scored": len(units), "n_pos": n_pos, "n_neg": len(units) - n_pos}
    if base is None:
        return {**out, "status": "uninformative", "note": "no positives or no negatives"}
    rng = random.Random(seed)
    diffs = []
    for _ in range(draws):
        s = aucs([rng.choice(units) for _ in units])
        if s is not None:
            diffs.append(s[0] - s[1])
    diffs.sort()
    lo, hi = diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]
    d = base[0] - base[1]
    status = ("uninformative" if len(units) < MIN_SCORED or n_pos < MIN_POSITIVES
              else "pass" if lo > 0 else "fail" if d <= 0 else "not_proven")
    return {**out, "auc_ours": round(base[0], 3), "auc_naive": round(base[1], 3), "diff": round(d, 3),
            "diff_95ci": [round(lo, 3), round(hi, 3)], "status": status}


def run(labels_path: str, run_paths: list[str], K: int = 10000, draws: int = 10000) -> dict:
    labels = json.loads(Path(labels_path).read_text())
    per, all_units = {}, []
    for p in run_paths:
        res = json.loads(Path(p).read_text())
        ours = tied_scores(labels, res, "all", K)
        naive = naive_scores(res, set(ours))
        units = compound_units(labels, ours, {k: v for k, v in naive.items() if k in ours})
        per[Path(p).name] = paired(units, K, draws)
        all_units += units
    per["pooled (scores from the separate pools of each half)"] = paired(all_units, K, draws)
    return per


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--draws", type=int, default=10000)
    a = ap.parse_args()
    print(json.dumps(run(a.labels, a.runs, draws=a.draws), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

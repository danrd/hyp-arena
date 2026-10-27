"""L3.11: calibration of the pairwise probabilities P(A>B) of the profile evidence_first against the ITP 2010 labels.

    python -m scripts.pairwise_calibration --labels data/backtest/itp_2010-12-31_labels.json \\
        --runs runs/stage5/itp2010_dev.abp.json runs/stage5/itp2010_test.abp.json

Units: pairs of regimens with different labels inside one half (the pairwise matrix is per pool). Forecast: P(positive beats negative).
Measures: Brier score, ECE in 5 equal bins of the forecast, 95% bootstrap intervals resampling compounds. The criterion is in
specs/validation-criteria.yaml (L3.11): pass = upper bound of the Brier interval below 0.25 and ECE not above 0.10; fail = Brier not below 0.25.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

PROFILE = "evidence_first"
BINS = 5


def pair_forecasts(labels: dict, res: dict) -> list[dict]:
    """One record per (positive, negative) pair of ranked regimens: forecast p = P(positive > negative), the compounds of both."""
    ids = res["meta"].get("ids") or [f"imp{i:03d}" for i in range(1, len(res["items"]) + 1)]
    pw = res["ranking"][PROFILE]["pairwise"]
    lab = {x["id"]: labels[pid] for pid, x in zip(ids, res["items"]) if x["outcome"] == "ranked" and pid in labels}
    pos = [h for h, v in lab.items() if v["label"] == 1]
    neg = [h for h, v in lab.items() if v["label"] == 0]
    return [{"p": float(pw[a][b]), "pos": lab[a]["compound"], "neg": lab[b]["compound"]}
            for a in pos for b in neg if a in pw and b in pw[a]]


def measures(rows: list[dict]) -> dict:
    if not rows:
        return {"brier": None, "ece": None, "n": 0}
    brier = sum((1 - r["p"]) ** 2 for r in rows) / len(rows)
    bins = defaultdict(list)
    for r in rows:
        # the forecast concerns "positive wins"; calibrate the side the model favours: bins on max(p, 1-p)
        fav = max(r["p"], 1 - r["p"])
        bins[min(BINS - 1, int((fav - 0.5) / 0.5 * BINS))].append((fav, 1.0 if (r["p"] >= 0.5) else 0.0))
    ece = sum(len(v) / len(rows) * abs(sum(f for f, _ in v) / len(v) - sum(y for _, y in v) / len(v)) for v in bins.values())
    return {"brier": brier, "ece": ece, "n": len(rows)}


def run(labels_path: str, run_paths: list[str], draws: int = 2000, seed: int = 0) -> dict:
    labels = json.loads(Path(labels_path).read_text())
    rows = []
    for p in run_paths:
        rows += pair_forecasts(labels, json.loads(Path(p).read_text()))
    base = measures(rows)
    by_compound = defaultdict(list)
    for r in rows:
        by_compound[r["pos"]].append(r)
        by_compound[r["neg"]].append(r)
    comps = list(by_compound)
    rng = random.Random(seed)
    bs, es = [], []
    for _ in range(draws):
        chosen = [rng.choice(comps) for _ in comps]
        seen, sample = set(), []
        for c in chosen:                                  # pairs of resampled compounds, each pair once per draw of its compounds
            for r in by_compound[c]:
                sample.append(r)
        m = measures(sample)
        if m["brier"] is not None:
            bs.append(m["brier"]); es.append(m["ece"])
    bs.sort(); es.sort()
    lo, hi = bs[int(0.025 * len(bs))], bs[int(0.975 * len(bs)) - 1]
    status = "fail" if base["brier"] >= 0.25 else "pass" if hi < 0.25 and base["ece"] <= 0.10 else "not_proven"
    forecasts = sorted(r["p"] for r in rows)
    return {"pairs": base["n"], "compounds": len(comps), "brier": round(base["brier"], 3), "brier_95ci": [round(lo, 3), round(hi, 3)],
            "ece": round(base["ece"], 3), "ece_95ci": [round(es[int(0.025 * len(es))], 3), round(es[int(0.975 * len(es)) - 1], 3)],
            "share_forecast_beyond_0.95": round(sum(1 for p in forecasts if p > 0.95 or p < 0.05) / len(forecasts), 3),
            "share_forecast_exactly_half": round(sum(1 for p in forecasts if abs(p - 0.5) < 0.02) / len(forecasts), 3), "status": status}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--draws", type=int, default=2000)
    a = ap.parse_args()
    print(json.dumps(run(a.labels, a.runs, a.draws), indent=1))


if __name__ == "__main__":
    main()

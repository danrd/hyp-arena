"""Calibration of the pool-diagnostics warnings (hyparena/diagnostics.py) on the pools we have, without model calls.

    python -m scripts.diagnostics_calibration --draws 30 --K 2000

For every pool of ranked hypotheses (indicator values from saved runs) and every profile it reports
  observed    number of varying indicators, share of ordered pairs, leading indicator and its share;
  by size     the same on random sub-pools of 10, 15, 20, 30 hypotheses (does a warning fire because the pool is small?);
  chance      the same after permuting every indicator column across the hypotheses independently (marginals kept,
              dependence between indicators and hypotheses destroyed): what a pool with no structure gives.
The warning thresholds are compared with these distributions in docs/rules-method.md.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from hyparena import diagnostics
from hyparena.aspid import aggregate, load_profiles
from hyparena.card import indicators as ind

POOLS = {
    "itp2010_dev": "runs/stage5/itp2010_dev.abp.json",
    "itp2010_test": "runs/stage5/itp2010_test.abp.json",
    "drugage2015": "runs/stage5/drugage_2015.json",
    "g003": "runs/stage5/g003.abp.json",
}


def load_values(path: str) -> tuple[dict, list]:
    res = json.loads(Path(path).read_text())
    specs = [s for s in ind.for_meta(res["meta"])]
    values = {x["id"]: dict(x["indicators"]) for x in res["items"] if x["outcome"] == "ranked" and x.get("indicators") is not None}
    return values, specs


def diagnose(values: dict, specs: list, profiles: dict, K: int) -> dict:
    items = [{"id": h, "outcome": "ranked", "indicators": v} for h, v in values.items()]
    ranking = {}
    for name, p in profiles.items():
        r = aggregate(values, specs, p, K=K, seed=0, k_top=min(5, len(values)))
        ranking[name] = {"order": r.order, "expected": r.expected, "std": r.std, "K": K}
    d = diagnostics.pool_diagnostics(items, ranking, [s.id for s in specs])
    return {"varying": len(d["varying"]), "n": d["ranked"], "pairs": d["pairs_ordered"],
            "lead": {n: (v["id"], v["share"]) for n, v in (d.get("leading") or {}).items()}, "warnings": len(d["warnings"])}


def permute(values: dict, specs: list, rng: random.Random) -> dict:
    ids = list(values)
    out = {h: {} for h in ids}
    for s in specs:
        col = [values[h].get(s.id) for h in ids]
        rng.shuffle(col)
        for h, v in zip(ids, col):
            out[h][s.id] = v
    return out


def summary(runs: list[dict], key) -> str:
    xs = sorted(key(r) for r in runs if key(r) is not None)
    if not xs:
        return "-"
    return f"{statistics.median(xs):.2f} [{xs[int(0.05 * (len(xs) - 1))]:.2f}; {xs[int(0.95 * (len(xs) - 1))]:.2f}]"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--draws", type=int, default=30)
    ap.add_argument("--K", type=int, default=2000)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    profiles = load_profiles()
    result = {}
    for name, path in POOLS.items():
        if not Path(path).exists():
            continue
        values, specs = load_values(path)
        rng = random.Random(0)
        obs = diagnose(values, specs, profiles, a.K)
        sizes = {}
        for m in (10, 15, 20, 30):
            if m < len(values):
                sizes[m] = [diagnose({h: values[h] for h in rng.sample(list(values), m)}, specs, profiles, a.K) for _ in range(a.draws)]
        chance = [diagnose(permute(values, specs, rng), specs, profiles, a.K) for _ in range(a.draws)]
        result[name] = {"observed": obs, "by_size": sizes, "chance": chance}
        print(f"\n== {name}: {obs['n']} ranked, {obs['varying']} of {len(specs)} indicators vary")
        for p in profiles:
            lead = obs["lead"].get(p)
            print(f"  {p:<16} pairs ordered {obs['pairs'][p]:.2f}  leading {lead[0]} {lead[1]:.2f}" if lead else f"  {p}")
        for m, runs in sizes.items():
            print(f"  size {m:>2}: varying {summary(runs, lambda r: r['varying'])}; pairs(evidence_first) {summary(runs, lambda r: r['pairs'].get('evidence_first'))}; "
                  f"lead share {summary(runs, lambda r: (r['lead'].get('evidence_first') or (None, None))[1])}; warnings>0 in {sum(r['warnings'] > 0 for r in runs)}/{len(runs)}")
        print(f"  chance : varying {summary(chance, lambda r: r['varying'])}; pairs(evidence_first) {summary(chance, lambda r: r['pairs'].get('evidence_first'))}; "
              f"lead share {summary(chance, lambda r: (r['lead'].get('evidence_first') or (None, None))[1])}; warnings>0 in {sum(r['warnings'] > 0 for r in chance)}/{len(chance)}")
    if a.out:
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

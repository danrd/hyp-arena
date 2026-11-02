"""Offline rule experiments on the calibration units (no model calls): E1 known result needs 2 independent sources, E3 reviews
count towards robustness, E4 an outcome paper does not count again for premises. 2026-11-02.

    python -m scripts.rule_experiments
"""
from __future__ import annotations

import itertools
import json
from dataclasses import replace

from hyparena.aspid import aggregate, load_profiles
from hyparena.backtest import PRIMARY_DROP, bootstrap_tied_auc, tied_auc
from hyparena.card import indicators as ind
from hyparena.card import rules
from hyparena.card.pipeline import reapply_rules
from scripts.calibration import CAL

FLAGS = {"E1": ("KNOWN_MIN_INDEPENDENT", 2, 1), "E3": ("REVIEWS_FOR_ROBUSTNESS", True, False), "E4": ("DEDUP_OUTCOME_PAPERS", True, False)}


def load():
    units, runs = {}, {}
    for st in (1, 2, 3):
        units.update({u["id"]: u for u in json.loads((CAL / f"units_{st}.json").read_text())})
        runs.update(json.loads((CAL / f"run_{st}_msearch.json").read_text()))
    return units, runs


def evaluate(units, runs, on: tuple[str, ...]) -> dict:
    rules.GRADED_CONTEXT = True
    for k, (name, val, off) in FLAGS.items():
        setattr(rules, name, val if k in on else off)
    R = {h: reapply_rules(r) for h, r in runs.items()}
    specs = [sp for sp in ind.for_meta(next(iter(R.values()))["meta"]) if sp.id not in PRIMARY_DROP]
    keep = {sp.id for sp in specs}
    values = {h: {k: v for k, v in (r["items"][0].get("indicators") or {}).items() if k in keep}
              for h, r in R.items() if r["items"][0]["outcome"] == "ranked"}
    prof = load_profiles()["evidence_first"]
    prof = replace(prof, tiers=[t for t in [t if isinstance(t, str) else [i for i in t if i in keep] for t in prof.tiers] if t])
    agg = aggregate(values, specs, prof, K=10000)
    base = {"known_result": 3.0, "ranked": 2.0, "filtered": 0.0}
    sc = {h: (base.get(R[h]["items"][0]["outcome"], 1.0) + agg.expected.get(h, 0.0), agg.std.get(h, 0.0)) for h in R}
    pos = [sc[h] for h in sc if units[h]["label"] == 1]
    neg = [sc[h] for h in sc if units[h]["label"] == 0]
    lo, hi = bootstrap_tied_auc(pos, neg)
    detail = {h: (units[h]["label"], R[h]["items"][0]["outcome"], (R[h]["items"][0].get("indicators") or {}).get("effect_level"),
                  (R[h]["items"][0].get("indicators") or {}).get("robustness"), (R[h]["items"][0].get("indicators") or {}).get("mechanism"),
                  round(sc[h][0], 3)) for h in R}
    return {"on": list(on), "auc": round(tied_auc(pos, neg), 3), "ci95": [round(lo, 3), round(hi, 3)], "detail": detail}


def main() -> None:
    units, runs = load()
    out = []
    for k in range(0, 4):
        for on in itertools.combinations(("E1", "E3", "E4"), k):
            r = evaluate(units, runs, on)
            out.append(r)
            print(f"{'+'.join(on) or 'baseline':10} AUC {r['auc']}  CI {r['ci95']}")
    for k, (name, val, off) in FLAGS.items():
        setattr(rules, name, off)
    (CAL / "rule_experiments.json").write_text(json.dumps(out, indent=1, default=str) + "\n")


if __name__ == "__main__":
    main()

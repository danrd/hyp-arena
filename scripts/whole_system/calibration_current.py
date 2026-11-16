"""The measures of specs/whole-system/calibration-current-2026-11-16.yaml on a set of calibration runs (free, no model call).

    python -m scripts.whole_system.calibration_current [--tags _v10 _cur]   # -> calibration/calibration_current.json

For each run tag (CAL_RUN_TAG of scripts/common/ablation.py): R3 (the AUC of the evidence balance, a gated hypothesis -1,
against the trial outcomes) with a bootstrap interval over trials, on all trials, on the 14 clean ones (step 4, first posted
2023-2026), on the others, and without the three texts that state the outcome; R2 (later RCTs and meta-analyses of a link
from its earlier records, weighted as the method weighs them: scripts/scoring/weight_variants.r2_auc) with its interval,
on the whole record pool and on the calibration records alone; coverage (links with a record), records per trial, the share
gated and the outcomes of the gated. Between the first two tags: the trials whose balance moves by more than 0.3.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import random
from collections import Counter

LEAK = {"NCT02402608", "NCT03372876", "NCT04893746"}   # H86, H96, H113 (specs/data/calibration-leak-2026-11-12.yaml)


def _boot(vals: list[tuple[float, int]], n: int = 2000, seed: int = 0) -> list[float]:
    from scripts.common.ablation import auc_of
    rnd, out = random.Random(seed), []
    for _ in range(n):
        a = auc_of([rnd.choice(vals) for _ in vals])
        if a is not None:
            out.append(a)
    out.sort()
    return [round(out[int(0.025 * len(out))], 3), round(out[int(0.975 * len(out)) - 1], 3)]


def measures(tag: str) -> dict:
    os.environ["CAL_RUN_TAG"] = tag
    from scripts.common import ablation, v34_check
    importlib.reload(v34_check)
    importlib.reload(ablation)
    from hyparena.scoring import rules_v32 as r32
    from scripts.scoring import record_weight_check as rw, weight_variants as wv
    importlib.reload(rw)
    units = ablation.units()
    clean = {u["id"] for u in json.loads((ablation.CAL / "units_4.json").read_text())}
    rows = {}
    for u in units:
        e = r32.evaluate(u["card"], u["cvs"], u["alts"], v36=True)
        recs = sum(len(cv.evidence) + len(cv.counterevidence) for cv in u["cvs"])
        rows[u["id"]] = {"label": u["label"], "gate": e.gate, "balance": -1.0 if e.gate != "pass" else e.chain_state,
                         "records": recs,
                         "links": len(u["cvs"]), "links_with_record": sum(bool(cv.evidence or cv.counterevidence) for cv in u["cvs"])}

    def r3(ids):
        vals = [(rows[i]["balance"], rows[i]["label"]) for i in ids]
        return {"n": len(vals), "auc": ablation.auc_of(vals), "ci95": _boot(vals)}
    allid = list(rows)
    out = {"tag": tag, "trials": len(rows),
           "R3": {"all": r3(allid), "clean_14": r3([i for i in allid if i in clean]),
                  "others": r3([i for i in allid if i not in clean]), "without_leak": r3([i for i in allid if i not in LEAK])}}
    refs = wv.r2_refs()
    cal_refs = [u for u in refs if u["link"][0] in rows]
    out["R2"] = {"all": {"targets": len(refs), "links": len({u["link"] for u in refs}), "auc": wv.r2_auc(refs)},
                 "calibration_only": {"targets": len(cal_refs), "links": len({u["link"] for u in cal_refs}),
                                      "auc": wv.r2_auc(cal_refs)}}
    rec = [r["records"] for r in rows.values()]
    gated = [r for r in rows.values() if r["gate"] != "pass"]
    out["coverage"] = {"links": sum(r["links"] for r in rows.values()),
                       "links_with_record": sum(r["links_with_record"] for r in rows.values()),
                       "records_per_trial_median": sorted(rec)[len(rec) // 2], "records_total": sum(rec),
                       "gated": len(gated), "gated_outcomes": dict(Counter(r["label"] for r in gated))}
    out["_balance"] = {i: r["balance"] for i, r in rows.items()}
    return out


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tags", nargs="+", default=["_v10", "_cur"])
    a = ap.parse_args(argv)
    res = [measures(t) for t in a.tags]
    out = {"runs": [{k: v for k, v in r.items() if k != "_balance"} for r in res]}
    if len(res) >= 2:
        b0, b1 = res[0]["_balance"], res[1]["_balance"]
        common = sorted(set(b0) & set(b1))
        moved = {i: [round(b0[i], 3), round(b1[i], 3)] for i in common if abs(b0[i] - b1[i]) > 0.3}
        out["moved_more_than_0.3"] = {"common_trials": len(common), "n": len(moved), "trials": moved}
    from scripts.common.ablation import CAL
    (CAL / "calibration_current.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()

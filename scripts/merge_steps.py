"""Free: the evidence balance with every step before the outcome as one place (by the weakest step with data, or by the
mean), against the current places (specs/merge-steps-2026-11-14.yaml). Same references as specs/empty-slots-2026-11-09.yaml:
R3 (calibration trial outcomes, AUC), the outside reader's trial balance (pack 8, Spearman), how many prospective units
move, and the rankings (Spearman of the expected score, top 10 kept)."""
from __future__ import annotations

import json

from scipy.stats import spearmanr

from hyparena.card import rules_v32 as r32
from scripts.empty_slots import prospective, r3_auc, ranks
from scripts.v34_check import CAL


def main() -> dict:
    # the approved-action rule looks drugs up in ChEMBL, which this environment cannot reach; it is the same in every variant
    from hyparena.card import rules_v3 as r3
    r3.established_by_approval = lambda claim, card: False
    from hyparena.tools import compounds as _cp                    # PubChem / ChEMBL are not reachable here: no lookups
    _cp._get = lambda url: None                                    # (the same in every variant; readiness from cache only)
    out = {}
    ans = {t["id"]: t["balance"] for t in json.loads((CAL.parents[1] / "reviews" / "argon-2026-11-08" / "pack_8_answer.json").read_text())["trials"]}
    for mode in ("separate", "min", "mean"):
        r32.STEPS_SLOT = mode
        print("mode", mode, flush=True)
        p = prospective()
        hs = [h for h in ans if h in p]
        sp = spearmanr([-1.0 if p[h][0] != "pass" else p[h][1] for h in hs], [ans[h] for h in hs]).statistic
        out[mode] = {"R3": round(r3_auc(), 3), "pack8_trial_spearman": round(float(sp), 3),
                     "balance": {h: v[1] for h, v in p.items()}, "rank": ranks(None)}
    r32.STEPS_SLOT = "separate"
    summ = {}
    base = out["separate"]
    for mode in ("min", "mean"):
        o = out[mode]
        changed = [h for h in base["balance"] if abs(base["balance"][h] - o["balance"][h]) > 1e-9]
        rk = {}
        for prof in ("evidence", "funding", "frontier"):
            a, b = base["rank"][prof], o["rank"][prof]
            hs = sorted(a)
            top = lambda d: set(sorted(d, key=lambda h: -d[h])[:10])
            rk[prof] = {"spearman": round(float(spearmanr([a[h] for h in hs], [b[h] for h in hs]).statistic), 3),
                        "top10_kept": len(top(a) & top(b))}
        summ[mode] = {"R3": o["R3"], "pack8_trial_spearman": o["pack8_trial_spearman"], "units_moved": len(changed),
                      "of": len(base["balance"]), "rankings": rk}
    summ["separate"] = {"R3": base["R3"], "pack8_trial_spearman": base["pack8_trial_spearman"]}
    return summ


if __name__ == "__main__":
    res = main()
    (CAL.parent / "merge_steps.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))

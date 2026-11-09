"""Free: v3.6 balance with empty slots counted (as now) vs skipped (specs/empty-slots-2026-11-09.yaml)."""
from __future__ import annotations

import json

from scipy.stats import spearmanr

from hyparena.card import rules_v32 as r32
from scripts.v34_check import CAL, PROS, parts


def r3_auc() -> float:
    from scripts.ablation import auc_of, units
    vals = []
    for u in units():
        e = r32.evaluate(u["card"], u["cvs"], u["alts"], v36=True)
        vals.append((-1.0 if e.gate != "pass" else e.chain_state, u["label"]))
    return auc_of(vals)


def prospective() -> dict:
    run = json.loads((PROS / "run_60.json").read_text())
    out = {}
    for h, r in run.items():
        it = r["items"][0]
        if it.get("card") and it.get("verification") and "v3" in it:
            card, cvs, alts = parts(it, h)
            e = r32.evaluate(card, cvs, alts, v36=True)
            out[h] = (e.gate, e.chain_state, e.support_share)
    return out


def ranks(bal: dict) -> dict:
    from scripts.profile_variants import expected, prospective as pax
    pa = pax()
    res = {}
    for prof, tiers in (("evidence", None), ("funding", None), ("frontier", None)):
        from hyparena.card import aspid_v3
        t = aspid_v3.load()[prof][0].tiers
        res[prof] = expected(pa, prof, t)
    return res


def main() -> dict:
    out = {}
    for mode in ("count", "skip"):
        r32.EMPTY_SLOTS = mode
        p = prospective()
        ans = {t["id"]: t["balance"] for t in json.loads((CAL.parents[1] / "reviews" / "argon-2026-11-08" / "pack_8_answer.json").read_text())["trials"]}
        hs = [h for h in ans if h in p]
        sp = spearmanr([-1.0 if p[h][0] != "pass" else p[h][1] for h in hs], [ans[h] for h in hs]).statistic
        out[mode] = {"R3": r3_auc(), "pack8_trial_spearman": round(float(sp), 3), "balance": {h: v[1] for h, v in p.items()},
                     "rank": ranks(None)}
    r32.EMPTY_SLOTS = "count"
    changed = [h for h in out["count"]["balance"] if abs(out["count"]["balance"][h] - out["skip"]["balance"][h]) > 1e-9]
    mv = {}
    for prof in ("evidence", "funding", "frontier"):
        a, b = out["count"]["rank"][prof], out["skip"]["rank"][prof]
        hs = sorted(a)
        top = lambda d: set(sorted(d, key=lambda h: -d[h])[:10])
        mv[prof] = {"spearman": round(float(spearmanr([a[h] for h in hs], [b[h] for h in hs]).statistic), 3), "top10_kept": len(top(a) & top(b))}
    res = {"R3": {m: out[m]["R3"] for m in out}, "pack8_trial_spearman": {m: out[m]["pack8_trial_spearman"] for m in out},
           "prospective_units_changed": f"{len(changed)}/{len(out['count']['balance'])}",
           "mean_balance": {m: round(sum(out[m]["balance"].values()) / len(out[m]["balance"]), 3) for m in out},
           "ranking_vs_count": mv}
    (CAL / "empty_slots.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))

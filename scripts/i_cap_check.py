"""Sensitivity of I to its cap (specs/informativeness-check-2026-11-08.yaml, cap_check). Free.

    python -m scripts.i_cap_check      # -> calibration/i_cap_check.json
"""
from __future__ import annotations

import datetime as dt
import json

from scipy.stats import spearmanr

from hyparena.card import aspid_v3
from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card import trend_genetics as tg
from hyparena.card import v3_extra
from scripts.ablation import units
from scripts.i_recalibration import measure
from scripts.pack6_analysis import D, SUP
from scripts.v34_check import CAL, PROS, parts

ARGON = CAL.parents[1] / "reviews" / "argon-2026-11-08"
CAPS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 1e6)   # 1e6 ("no cap") is invalid: I is rounded to 4 decimals


def prospective_axes():
    from scripts.prospective import endpoint_clinical
    ax, Is = {}, {}
    for h, r in json.loads((PROS / "run_60.json").read_text()).items():
        it = r["items"][0]
        if not (it.get("card") and it.get("verification") and "v3" in it):
            continue
        card, cvs, alts = parts(it, h)
        e = r32.evaluate(card, cvs, alts, v36=True)
        Is[h] = e.I
        if e.gate != "pass":
            continue
        as_of = r["meta"].get("as_of") or dt.date.today().isoformat()
        ext = v3_extra.extras(card, cvs, it["v3"], as_of)
        with r32.method():
            N = nv.novelty(card, cvs, e)
        ext.update({"support_share": e.support_share, "chain_state": e.chain_state, "N": N, "ai_role": card.ai_role,
                    "endpoint_clinical": endpoint_clinical(60, h), "trend_pubmed": tg.trend_pubmed(card, as_of)[0]})
        ax[h] = ({"P": e.P, "scope": e.scope, "I": e.I, "headroom_I": e.headroom_I, "gate": "pass"}, ext)
    return ax, Is


def main() -> dict:
    argon = {t["id"]: t for t in json.loads((ARGON / "pack_6_answer.json").read_text())["trials"]}
    key = json.loads((ARGON / "pack_6_key.json").read_text())
    from hyparena.card import alternatives_d
    out, base_scores = {}, None
    cal = units()
    order = [1.5] + [c for c in CAPS if c != 1.5]
    for cap in order:
        r3.I_CAP = cap
        ax, Is = prospective_axes()
        ids = sorted(h for h in Is if h in argon)
        # I from Argon's d and our a under the same cap
        I_arg = []
        for h in ids:
            jd = alternatives_d.judged().get(h, {})
            s = sum(ka["a_v36"] * max(D[a["d_positive"]], D[a["d_negative"]])
                    for a in argon[h]["alternatives"] for aid, ka in key[h]["alternatives"].items() if aid == a["id"])
            I_arg.append(min(1.0, s / cap))
        scores = {}
        for p in aspid_v3.load():
            agg = aspid_v3.rank(ax, p, K=4000)
            scores[p] = agg.expected
        row = {"saturated_I_1": round(sum(v >= 0.9999 for v in Is.values()) / len(Is), 3),
               "I_0": round(sum(v == 0 for v in Is.values()) / len(Is), 3),
               "spearman_argon_informativeness": round(float(spearmanr([Is[h] for h in ids], [argon[h]["informativeness"] for h in ids]).statistic), 3),
               "spearman_I_with_argon_d": round(float(spearmanr([Is[h] for h in ids], I_arg).statistic), 3)}
        if base_scores is None:
            base_scores = scores
        for p in scores:
            ks = sorted(scores[p])
            top = lambda d: set(sorted(ks, key=lambda k: -d[k])[:10])
            row[f"{p}_rho_vs_1.5"] = round(float(spearmanr([scores[p][k] for k in ks], [base_scores[p][k] for k in ks]).statistic), 3)
            row[f"{p}_top10_kept"] = len(top(scores[p]) & top(base_scores[p]))
        row["calibration"] = measure(cal)
        out[str(cap if cap < 1e5 else "no cap")] = row
    r3.I_CAP = 1.5
    (CAL / "i_cap_check.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    res = main()
    for k, v in res.items():
        c = v["calibration"]
        print(f"cap {k:>6}: I=1 {v['saturated_I_1']:.2f} I=0 {v['I_0']:.2f} | argon informativeness rho {v['spearman_argon_informativeness']:.3f} "
              f"| argon-d I rho {v['spearman_I_with_argon_d']:.3f} | ranks rho ev/fu/fr {v['evidence_rho_vs_1.5']}/{v['funding_rho_vs_1.5']}/{v['frontier_rho_vs_1.5']} "
              f"top10 {v['evidence_top10_kept']}/{v['funding_top10_kept']}/{v['frontier_top10_kept']} | cal I {c['I_auc']} ev {c['evidence']['all']} fu {c['funding']['all']} fr {c['frontier']['all']}")

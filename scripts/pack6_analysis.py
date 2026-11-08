"""Analysis of Argon pack 6 (specs/informativeness-check-2026-11-08.yaml, measures fixed before sending). Free.

    python -m scripts.pack6_analysis
"""
from __future__ import annotations

import json
from collections import Counter

from scipy.stats import spearmanr

from scripts.pack6_informativeness import DIR

D = {"eliminated": 1.0, "weakened": 0.5, "unchanged": 0.0}
SUP = {"none": 0.0, "weak": 1 / 3, "moderate": 2 / 3, "strong": 1.0}
I_CAP = 1.5


def wkappa(pairs: list[tuple[float, float]], levels=(0.0, 0.5, 1.0)) -> float:
    """Linear-weighted Cohen kappa on ordered levels."""
    n, k = len(pairs), len(levels)
    idx = {v: i for i, v in enumerate(levels)}
    w = lambda i, j: 1 - abs(i - j) / (k - 1)
    po = sum(w(idx[a], idx[b]) for a, b in pairs) / n
    ca, cb = Counter(idx[a] for a, _ in pairs), Counter(idx[b] for _, b in pairs)
    pe = sum(w(i, j) * ca[i] * cb[j] for i in range(k) for j in range(k)) / n ** 2
    return round((po - pe) / (1 - pe), 3)


def main() -> dict:
    ans = {t["id"]: t for t in json.loads((DIR / "pack_6_answer.json").read_text())["trials"]}
    key = json.loads((DIR / "pack_6_key.json").read_text())
    dp, gen, sup_pairs, our_sup, arg_sup = [], Counter(), [], [], []
    I = {"ours": [], "argon_d_our_a": [], "argon_d_argon_a": [], "argon_all": [], "argon_informativeness": []}
    ad_from_no, ad_total, elim_with_feature, elim = 0.0, 0.0, 0, 0
    recall = 0
    for h, k in key.items():
        t = ans.get(h)
        if not t:
            continue
        aa = {a["id"]: a for a in t["alternatives"]}
        s1 = s2 = 0.0
        sup1 = sup2 = False
        for aid, ka in k["alternatives"].items():
            a = aa.get(aid)
            if not a:
                continue
            ours_d = max(D[ka["on_positive"]], D[ka["on_negative"]])
            arg_d = max(D[a["d_positive"]], D[a["d_negative"]])
            dp.append((ours_d, arg_d))
            gen[a["genuine"]] += 1
            ad_total += ka["a_v36"] * ours_d
            if a["genuine"] == "no":
                ad_from_no += ka["a_v36"] * ours_d
            if arg_d == 1.0:
                elim += 1
                elim_with_feature += bool(a.get("separating_feature"))
            our_sup.append(ka["a_v36"])
            arg_sup.append(SUP[a["support"]])
            sup_pairs.append((ka["a_v36"] > 0, SUP[a["support"]] >= 1 / 3))
            s1 += ka["a_v36"] * arg_d
            s2 += SUP[a["support"]] * arg_d
            sup1 |= ka["a_v36"] > 0
            sup2 |= SUP[a["support"]] > 0
        s3 = s2 + sum(SUP[m["support"]] * max(D[m["d_positive"]], D[m["d_negative"]]) for m in t.get("missing_alternatives", []))
        recall += any(SUP[m["support"]] >= 2 / 3 and max(D[m["d_positive"]], D[m["d_negative"]]) >= 0.5
                      for m in t.get("missing_alternatives", []))
        I["ours"].append(k["I_v36"])
        I["argon_d_our_a"].append(min(1.0, s1 / I_CAP) if sup1 else 0.0)
        I["argon_d_argon_a"].append(min(1.0, s2 / I_CAP) if sup2 else 0.0)
        I["argon_all"].append(min(1.0, s3 / I_CAP))
        I["argon_informativeness"].append(t.get("informativeness"))
    rho = lambda a, b: round(float(spearmanr(a, b).statistic), 3)
    out = {
        "trials": len(I["ours"]), "alternatives": len(dp),
        "d": {"weighted_kappa": wkappa(dp), "confusion_ours_to_argon": dict(Counter(f"{a}->{b}" for a, b in dp).most_common()),
              "argon_eliminated": elim, "eliminated_with_feature": elim_with_feature},
        "genuine": dict(gen), "share_of_our_sum_ad_from_not_genuine": round(ad_from_no / ad_total, 3) if ad_total else None,
        "a": {"spearman_ours_vs_argon": rho(our_sup, arg_sup),
              "supported_agreement": round(sum(x == y for x, y in sup_pairs) / len(sup_pairs), 3),
              "ours_supported": sum(x for x, _ in sup_pairs), "argon_supported": sum(y for _, y in sup_pairs)},
        "I": {"spearman_ours_vs_argon_d_our_a": rho(I["ours"], I["argon_d_our_a"]),
              "spearman_ours_vs_argon_d_argon_a": rho(I["ours"], I["argon_d_argon_a"]),
              "spearman_ours_vs_argon_all": rho(I["ours"], I["argon_all"]),
              "spearman_ours_vs_argon_informativeness": rho(I["ours"], I["argon_informativeness"]),
              "spearman_argon_d_argon_a_vs_argon_informativeness": rho(I["argon_d_argon_a"], I["argon_informativeness"]),
              "mean": {k: round(sum(v) / len(v), 3) for k, v in I.items()}},
        "recall_missing_supported_share": round(recall / len(I["ours"]), 3),
    }
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

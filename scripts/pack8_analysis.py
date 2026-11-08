"""Analysis of Argon pack 8 (specs/balance-check-2026-11-08.yaml, measures fixed before sending). Free (PubMed for PMIDs).

    python -m scripts.pack8_analysis
"""
from __future__ import annotations

import json
from collections import Counter

from scipy.stats import spearmanr

from hyparena.tools import pubmed
from scripts.pack8_balance import DIR

STR = {"weak": 1 / 3, "moderate": 2 / 3, "strong": 1.0, "none": 0.0}


def signed(v: dict) -> float:
    s = STR.get(v.get("strength"), 0.0)
    return {"supported": s, "refuted": -s}.get(v.get("verdict"), 0.0)


def main() -> dict:
    ans = {t["id"]: t for t in json.loads((DIR / "pack_8_answer.json").read_text())["trials"]}
    key = json.loads((DIR / "pack_8_key.json").read_text())
    ours, theirs, sign, danger, verd = [], [], Counter(), [], Counter()
    rec_hits = rec_all = 0
    pm_all = set()
    for h, k in key.items():
        t = ans.get(h)
        if not t:
            continue
        al = {l["id"]: l for l in t["links"]}
        for cid, lk in k["links"].items():
            a = al.get(cid)
            if not a:
                continue
            s_our, s_arg = 2 * lk["S"] - 1, signed(a)
            ours.append(s_our)
            theirs.append(s_arg)
            verd[a["verdict"]] += 1
            so = 0 if abs(s_our) < 0.1 else (1 if s_our > 0 else -1)
            sa = 0 if s_arg == 0 else (1 if s_arg > 0 else -1)
            sign[f"{so}->{sa}"] += 1
            if a["verdict"] == "refuted" and a.get("strength") in ("moderate", "strong") and s_our > 1 / 3:
                danger.append({"trial": h, "link": cid, "ours": round(s_our, 2), "argon": f"refuted {a['strength']}",
                               "pmids_against": a.get("pmids_against", [])})
            ps = set(a.get("pmids_for", []) + a.get("pmids_against", []))
            pm_all |= ps
            rec_all += len(ps)
            rec_hits += len(ps & set(lk["record_pmids"]))
    meta = pubmed.fetch(sorted(pm_all))
    ids = [h for h in key if h in ans]
    bal_o = [(-1.0 if key[h]["gate"] != "pass" else key[h]["balance_v36"]) for h in ids]
    bal_a = [ans[h]["balance"] for h in ids]
    agree = sum(v for k_, v in sign.items() if k_.split("->")[0] == k_.split("->")[1])
    return {"links": len(ours), "argon_verdicts": dict(verd),
            "link_spearman": round(float(spearmanr(ours, theirs).statistic), 3),
            "sign_agreement": round(agree / len(ours), 3), "sign_table_ours_to_argon": dict(sign.most_common()),
            "trial_spearman": round(float(spearmanr(bal_o, bal_a).statistic), 3),
            "mean_balance": {"ours": round(sum(bal_o) / len(bal_o), 3), "argon": round(sum(bal_a) / len(bal_a), 3)},
            "missed_refutations": danger,
            "pmids": {"distinct": len(pm_all), "found_in_pubmed": sum(p in meta for p in pm_all),
                      "dated_2026_or_earlier": sum(1 for p in pm_all if p in meta and (meta[p].get("year") or "9999")[:4] <= "2026")},
            "recall_of_argon_key_papers_in_our_records": f"{rec_hits}/{rec_all}"}


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

"""Analysis of Argon pack 7 (specs/novelty-check-2026-11-08.yaml, measures fixed before sending). Free (PubMed for PMIDs).

    python -m scripts.pack7_analysis
"""
from __future__ import annotations

import json
from collections import Counter

from hyparena.tools import pubmed
from scripts.pack6_analysis import wkappa
from scripts.pack7_novelty import DIR

LAD = {"new_context": 0, "translation": 1, "analog": 2, "new_combination": 3, "new_link": 4}
LINK = {"new_context": 0, "translation": 1, "analog": 2, "new_link": 3}


def main() -> dict:
    ans = {t["id"]: t for t in json.loads((DIR / "pack_7_answer.json").read_text())["trials"]}
    key = json.loads((DIR / "pack_7_key.json").read_text())
    pm = sorted({p for t in ans.values() for p in t.get("defining_pmids", []) + [x for l in t.get("links", []) for x in l.get("pmids", [])]
                 + ([t["known_result_pmid"]] if t.get("known_result_pmid") else [])})
    meta = pubmed.fetch(pm)
    ok = lambda p: p in meta and (meta[p].get("year") or "9999")[:4].isdigit() and int(meta[p]["year"][:4]) <= 2026
    conf, pairs, unknown, direction = Counter(), [], Counter(), Counter()
    analog_to = Counter()
    for h, k in key.items():
        t = ans.get(h)
        if not t:
            continue
        o, a = k["N"] or "unknown", t["novelty"]
        conf[f"{o}->{a}"] += 1
        if o == "analog":
            analog_to[a] += 1
        if o in LAD and a in LAD:
            pairs.append((LAD[o] / 4, LAD[a] / 4))
            valid = any(ok(p) for p in t.get("defining_pmids", []))
            if valid:
                direction["argon_nearer_known" if LAD[a] < LAD[o] else "argon_farther" if LAD[a] > LAD[o] else "same"] += 1
            else:
                direction["no_valid_pmid"] += 1
        else:
            unknown[f"ours {'unknown' if o == 'unknown' else 'level'} / argon {'unknown' if a == 'unknown' else 'level'}"] += 1
    lp = []
    for h, k in key.items():
        t = ans.get(h)
        if not t:
            continue
        al = {l["id"]: l["level"] for l in t.get("links", [])}
        for cid, ol in k["link_levels"].items():
            if cid in al and al[cid] in LINK and ol in LINK:
                lp.append((LINK[ol] / 3, LINK[al[cid]] / 3))
    defining = [p for t in ans.values() for p in t.get("defining_pmids", [])]
    in_ours = sum(1 for h, t in ans.items() for p in t.get("defining_pmids", []) if p in set(key.get(h, {}).get("our_record_pmids", [])))
    return {"trials": len(ans), "confusion_ours_to_argon": dict(conf.most_common()),
            "outcome_N_weighted_kappa": wkappa(pairs, levels=tuple(i / 4 for i in range(5))), "both_levelled": len(pairs),
            "unknown": dict(unknown), "our_analog_to": dict(analog_to), "direction": dict(direction),
            "link_levels_weighted_kappa": wkappa(lp, levels=tuple(i / 3 for i in range(4))), "links_compared": len(lp),
            "pmids": {"distinct": len(pm), "found_and_by_2026": sum(ok(p) for p in pm), "not_found": [p for p in pm if p not in meta]},
            "defining_pmids_in_our_records": f"{in_ours}/{len(defining)}",
            "known_result_argon": sum(bool(t.get("known_result")) for t in ans.values())}


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

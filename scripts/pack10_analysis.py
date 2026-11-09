"""Analysis of Argon pack 10 (specs/sources-argon-2026-11-09.yaml). Free.

    python -m scripts.pack10_analysis
"""
from __future__ import annotations

import json
from collections import Counter

from hyparena.card import rules_v32 as r32
from scripts.pack10_sources import DIR
from scripts.v34_check import CAL, PROS, parts

SIGN = {"supported": 1, "refuted": -1, "mixed": 0, "no_evidence": 0}


def main() -> dict:
    ans = json.loads((DIR / "pack_10_answer.json").read_text())["items"]
    key = json.loads((DIR / "pack_10_key.json").read_text())
    run = json.loads((PROS / "run_60.json").read_text())
    pc, ch, crit = Counter(), Counter(), []
    for it in ans:
        for p in it["papers"]:
            b = p.get("B") or {}
            pc[b.get("status", "missing")] += 1
            if b.get("status") != "read":
                continue
            for c in b.get("changed") or []:
                ch[c] += 1
            fa, fb = p["A"].get("finding"), b.get("finding")
            if fa != fb or "adds_finding" in (b.get("changed") or []) or "stance" in (b.get("changed") or []):
                crit.append(f"{it['id']} PMID {p['pmid']}: {fa} -> {fb}")
    links = []
    for it in ans:
        k = key[it["id"]]
        card, cvs, alts = parts(run[k["unit"]]["items"][0], k["unit"])
        e = r32.evaluate(card, cvs, alts, v36=True)
        s = 2 * e.links[k["claim"]][0] - 1 if k["claim"] in e.links else None
        links.append({"id": it["id"], "ours": round(s, 2) if s is not None else None,
                      "A": it["verdict_A"]["verdict"], "B": it["verdict_B"]["verdict"], "C": it["verdict_C"]["verdict"]})
    read = pc.get("read", 0)
    out = {"papers": sum(pc.values()), "full_text_status": dict(pc), "changed_fields_among_read": dict(ch.most_common()),
           "critical_changes": crit, "critical_share": f"{len(crit)}/{read} = {len(crit) / read:.2f}" if read else None,
           "links": links,
           "verdict_changes": {"A_to_B": sum(l["A"] != l["B"] for l in links), "B_to_C": sum(l["B"] != l["C"] for l in links), "of": len(links)},
           "ours_sign_vs": {v: sum(1 for l in links if l["ours"] is not None and (0 if abs(l["ours"]) < 0.1 else (1 if l["ours"] > 0 else -1)) == SIGN[l[v]]) for v in ("A", "B", "C")}}
    (CAL / "pack10_analysis.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))

"""Analysis of Argon pack 9 (specs/reading-gold-2026-11-08.yaml, measures fixed before sending). Free.

    python -m scripts.pack9_analysis
"""
from __future__ import annotations

import json
from collections import Counter

from hyparena.card.models import ClaimVerification
from scripts.pack9_reading import DIR
from scripts.reread_analysis import reread
from scripts.reread_v11 import items
from scripts.v34_check import CAL, PROS


def main() -> dict:
    ans = {i["id"]: i for i in json.loads((DIR / "pack_9_answer.json").read_text())["items"]}
    key = json.loads((DIR / "pack_9_key.json").read_text())
    orig = {f"{h}|{cv.id}": cv for h, _, _, cvs, _ in items("prospective") for cv in cvs}
    second = {f"{h}|{c}": cv for h, d in reread("prospective", "v9").items() for c, cv in d.items()}
    pilot = {k: ClaimVerification.model_validate(v["cv"]) for k, v in json.loads((PROS / "pilot_crosslink.json").read_text()).items()}
    gold = Counter(p["finding"] for i in ans.values() for p in i["papers"])
    out = {"pairs": sum(gold.values()), "argon_findings": dict(gold)}
    for name, rd in (("original", orig), ("second_v9", second), ("pilot", pilot)):
        tp = fn = fp = 0
        stance_ok = stance_n = 0
        missed = []
        for iid, it in ans.items():
            k = f"{key[iid]['unit']}|{key[iid]['claim']}"
            cv = rd.get(k)
            recs = {}
            if cv:
                for side, lst in (("for", cv.evidence), ("against", cv.counterevidence)):
                    for r in lst:
                        recs.setdefault(r.record_id.replace("PMID:", ""), side)
            gold_p = {p["pmid"] for p in it["papers"]}
            for p in it["papers"]:
                has = p["pmid"] in recs
                if p["finding"] in ("for", "against"):
                    if has:
                        tp += 1
                        stance_n += 1
                        stance_ok += recs[p["pmid"]] == p["finding"]
                    else:
                        fn += 1
                        missed.append(f"{iid} {p['pmid']} {p['finding']} {p['design']}")
                elif has:
                    fp += 1
            out.setdefault("records_outside_the_gold_papers", {})[name] = sum(1 for k2 in [None] if False)
        out[name] = {"recall": f"{tp}/{tp + fn} = {tp / (tp + fn):.2f}" if tp + fn else None,
                     "precision": f"{tp}/{tp + fp} = {tp / (tp + fp):.2f}" if tp + fp else None,
                     "stance_agreement": f"{stance_ok}/{stance_n}", "missed": missed}
    out.pop("records_outside_the_gold_papers", None)
    (CAL / "pack9_analysis.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))

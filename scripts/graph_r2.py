"""Argon's graph on the v3.6 rules: R2 and the evidence balance, ours vs graph vs union (specs/sources-experiment-2026-11-07.yaml,
graph_v36_2026_11_08). Free.

    python -m scripts.graph_r2      # -> calibration/graph_r2.json
"""
from __future__ import annotations

import json

from hyparena.backtest import tied_auc
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification
from hyparena.tools import pubmed
from scripts.ablation import units
from scripts.argon_check import SRC, as_record, check_quotes
from scripts.ceiling import CAL
import scripts.record_weight_check as m


def main() -> dict:
    data = json.loads(SRC.read_text())["hypotheses"]
    us = {u["id"]: u for u in units()}
    sources = {"ours": {}, "graph": {}, "union": {}}
    for h in data:
        u = us.get(h["id"])
        if not u:
            continue
        good = [x for x in check_quotes(h.get("graph", []), h.get("cutoff") or u["as_of"]) if x["_quote_ok"] and x["_before_cutoff"]]
        by = {c.id: c for c in u["cvs"]}
        g, un = [], []
        for cl in r3.chain(u["card"]):
            ev = [as_record(x) for x in good if x["link"] == cl.id and x.get("stance") == "supports"]
            ce = [as_record(x) for x in good if x["link"] == cl.id and x.get("stance") == "refutes"]
            g.append(ClaimVerification(id=cl.id, evidence=ev, counterevidence=ce))
            o = by.get(cl.id) or ClaimVerification(id=cl.id)
            have = {r.record_id for r in o.evidence + o.counterevidence}
            un.append(ClaimVerification(id=cl.id, evidence=o.evidence + [r for r in ev if r.record_id not in have],
                                        counterevidence=o.counterevidence + [r for r in ce if r.record_id not in have]))
        sources["ours"][h["id"]] = list(by.values())
        sources["graph"][h["id"]] = g
        sources["union"][h["id"]] = un
    out = {}
    for name, cvmap in sources.items():
        rows, pos, neg = [], [], []
        for h, cvs in cvmap.items():
            u = us[h]
            claims = {c.id: c for c in u["card"].claims}
            for cv in cvs:
                cl = claims.get(cv.id)
                if cl is None:
                    continue
                for side, lst in (("for", cv.evidence), ("against", cv.counterevidence)):
                    for rec in lst:
                        w = r32.current_weight(rec, cl, side == "against")
                        if w > 0:
                            rows.append({"unit": h, "claim": cv.id, "side": side, "w": w, "rec": rec, "group": r32.group_key(rec),
                                         "pmid": rec.record_id.replace("PMID:", "")})
            e = r32.evaluate(u["card"], cvs, u["alts"], v36=True)
            (pos if u["label"] == 1 else neg).append((-1.0 if e.gate != "pass" else e.chain_state, 0))
        meta = pubmed.fetch(sorted({r["pmid"] for r in rows}))
        for r in rows:
            y = (meta.get(r["pmid"], {}).get("year") or "")[:4]
            r["year"], r["dsg"] = (int(y) if y.isdigit() else None), r3.record_design(r["rec"])
        refs = m.build_refs(rows)
        f = lambda x: m.link_state_mode(x["records"], "loglr_sum")
        out[name] = {"records": len(rows), "R2": m.auc(refs["R2"], f), "R2_targets": len(refs["R2"]),
                     "R2_against_targets": sum(1 for x in refs["R2"] if x["label"] == 0),
                     "balance_auc_15": round(tied_auc(pos, neg), 3)}
    (CAL / "graph_r2.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))

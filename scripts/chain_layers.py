"""Argon's layers 3-4 on the calibration, free (user decision 2026-11-08): the weakest link as a hard gate and convergence of
independent kinds of evidence; plus "surprise" as the inverse of the models' probability (for reference).

    python -m scripts.chain_layers     # -> calibration/chain_layers.json
"""
from __future__ import annotations

import json
import math

from hyparena.backtest import tied_auc
from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from scripts.ablation import units
from scripts.ceiling import CAL

KIND = {"cells": "cells", "animal": "animal", "observational": "human_observational", "non_randomised": "human_trial",
        "rct": "human_trial", "meta_analysis": "synthesis", "review": "synthesis"}


def layers(u: dict) -> dict:
    card, cvs = u["card"], u["cvs"]
    e = r32.evaluate(card, cvs, u["alts"], v34=True)
    pre, out = nv.slots(card)
    slots = [(sl, False) for sl in pre] + ([(out, True)] if out else [])
    S = [nv._slot_S(e, sl, o) for sl, o in slots]
    a = [max(0.0, 2 * (s - 0.5)) for s in S]
    by = {c.id: c for c in cvs}
    claims = {c.id: c for c in r3.chain(card)}
    kinds, groups = set(), set()
    for cid, cl in claims.items():
        cv = by.get(cid)
        for r in (cv.evidence if cv else []):
            if r32.record_weight(r, cl, False, True) > 0:
                kinds.add(KIND.get(r3.record_design(r), "other"))
                groups.add(r32.group_key(r))
    return {"gate": e.gate, "P34": e.P, "support_share": e.support_share, "weakest_support": min(a) if a else 0.0,
            "product_S": math.prod(S) if S else 0.5, "kinds": len(kinds), "human_kinds": len(kinds & {"human_trial", "human_observational", "synthesis"}),
            "independent_sources": len(groups), "slots": len(slots)}


def main() -> dict:
    us = units()
    cons = {r["id"]: r for r in json.loads((CAL / "llm_consensus_summary.json").read_text())["rows"]}
    rows = []
    for u in us:
        x = layers(u)
        if x["gate"] != "pass":
            x.update({k: -1.0 for k in ("P34", "support_share", "weakest_support", "product_S")})
        m = (cons.get(u["id"]) or {}).get("prob")
        rows.append({"id": u["id"], "label": u["label"], **x, "surprise": None if m is None else 1 - m})

    def auc(k):
        pts = [(r[k], r["label"]) for r in rows if r.get(k) is not None]
        pos, neg = [(v, 0) for v, l in pts if l == 1], [(v, 0) for v, l in pts if l == 0]
        return (round(tied_auc(pos, neg), 3), len(pts)) if pos and neg else None
    from collections import Counter
    from scipy.stats import spearmanr
    keys = ("P34", "support_share", "weakest_support", "product_S", "kinds", "human_kinds", "independent_sources", "surprise")
    sep = {k: {"distinct": len({r[k] for r in rows}), "top_share": round(Counter(r[k] for r in rows).most_common(1)[0][1] / len(rows), 3)} for k in keys}
    rho = {f"{a}~{b}": round(float(spearmanr([r[a] for r in rows if r[a] is not None and r[b] is not None],
                                              [r[b] for r in rows if r[a] is not None and r[b] is not None]).statistic), 3)
           for i, a in enumerate(keys) for b in keys[i + 1:]}
    out = {"n": len(rows), "auc": {k: auc(k) for k in keys}, "separation": sep, "rho_over_0.7": {k: v for k, v in rho.items() if abs(v) >= 0.7}}
    (CAL / "chain_layers.json").write_text(json.dumps({"summary": out, "rows": rows}, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

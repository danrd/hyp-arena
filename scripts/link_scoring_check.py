"""specs/link-scoring-2026-11-08.yaml: A (chain state), B (null weighted by power), G (silent links) on the calibration (AUC)
and on calibration + prospective (admission rule). Free.

    python -m scripts.link_scoring_check     # -> calibration/link_scoring_check.json
"""
from __future__ import annotations

import json
from collections import Counter

from scipy.stats import spearmanr

from hyparena.backtest import tied_auc
from hyparena.card import rules_v32 as r32
from scripts.ablation import units
from scripts.ceiling import CAL
from scripts.v34_check import PROS, parts


def vals(card, cvs, alts) -> dict:
    a = r32.evaluate(card, cvs, alts, v34=True)
    b = r32.evaluate(card, cvs, alts, v34=True, null_power=True)
    g = lambda e, x: -1.0 if e.gate != "pass" else x
    return {"gate": a.gate, "P": g(a, a.P), "support_share": g(a, a.support_share), "chain_state": g(a, a.chain_state),
            "P_B": g(b, b.P), "chain_state_B": g(b, b.chain_state), "silent_share": a.silent_share, "I": a.I, "scope": a.scope}


def main() -> dict:
    rows = []
    for u in units():
        rows.append({"id": u["id"], "sample": "calibration", "label": u["label"], **vals(u["card"], u["cvs"], u["alts"])})
    for h, r in json.loads((PROS / "run_60.json").read_text()).items():
        it = r["items"][0]
        if it.get("card") and it.get("verification") and "v3" in it:
            rows.append({"id": h, "sample": "prospective", "label": None, **vals(*parts(it))})
    cal = [r for r in rows if r["label"] in (0, 1)]

    def auc(k):
        pos, neg = [(r[k], 0) for r in cal if r["label"] == 1], [(r[k], 0) for r in cal if r["label"] == 0]
        return round(tied_auc(pos, neg), 3)
    keys = ("P", "support_share", "chain_state", "P_B", "chain_state_B", "silent_share", "I")
    ok = [r for r in rows if r["gate"] == "pass"]
    sep = {k: {"distinct": len({round(r[k], 3) for r in ok}), "top_share": round(Counter(round(r[k], 3) for r in ok).most_common(1)[0][1] / len(ok), 3)} for k in keys}
    rho = {f"{a}~{b}": round(float(spearmanr([r[a] for r in ok], [r[b] for r in ok]).statistic), 3) for i, a in enumerate(keys) for b in keys[i + 1:]}
    silent = Counter((r["silent_share"] > 0) for r in ok)
    out = {"calibration": len(cal), "units": len(ok), "auc": {k: auc(k) for k in keys}, "separation": sep, "rho": rho,
           "with_a_silent_slot": silent.get(True, 0)}
    (CAL / "link_scoring_check.json").write_text(json.dumps({"summary": out, "rows": rows}, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

"""Method v3.4 check on the saved runs, no model calls (specs/v34-frontier-2026-11-07.yaml): P v3.4 vs v3.3 on the
calibration (tied AUC, exploration only), and the admission rule (separation, |Spearman rho| < 0.7) for the new indicators on
the 74 calibration + 60 prospective units. PubMed counts (literature density) are free and cached.

    python -m scripts.v34_check        # writes $KG_DIR/hypothesis_sources/calibration/v34_check.json
"""
from __future__ import annotations

import json
from collections import Counter

from hyparena.backtest import tied_auc
from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v32 as r32
from hyparena.card import v3_extra
from hyparena.card.models import ClaimVerification, HypothesisCard
from scripts.ctgov_outcomes import KG

CAL = KG / "hypothesis_sources" / "calibration"
PROS = KG / "hypothesis_sources" / "prospective"
W_ORDER = ("local", "organ", "hallmark")


def parts(it: dict):
    card = HypothesisCard.model_validate(it["card"])
    cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
    alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
    return card, cvs, alts


def row(it: dict, as_of: str) -> dict:
    card, cvs, alts = parts(it)
    e33 = r32.evaluate(card, cvs, alts, fold=True, neutral_unverified=True)
    e34 = r32.evaluate(card, cvs, alts, v34=True)
    lev, wpot, bott = nv.leverage(card, cvs, e34)
    ext = v3_extra.extras(card, cvs, it["v3"], as_of)
    return {"gate": e34.gate, "P33": e33.P, "P34": e34.P, "ss33": e33.support_share, "ss34": e34.support_share, "I": e34.I,
            "I_headroom": it["v3"].get("headroom_I"), "W": e34.scope, "against_share": ext.get("against_share"),
            "feasibility": ext.get("feasibility"), "N": nv.novelty(card, cvs, e34), "density": nv.literature_density(card, as_of),
            "leverage": lev, "W_potential": wpot, "bottleneck": bott, "links": len(e34.links)}


def units() -> list[dict]:
    out = []
    for s in (1, 2, 3, 4, 5):
        us = {u["id"]: u for u in json.loads((CAL / f"units_{s}.json").read_text())}
        for h, r in json.loads((CAL / f"run_{s}_v10.json").read_text()).items():
            it = r["items"][0]
            if not it.get("card") or not it.get("verification") or "v3" not in it:
                continue
            as_of = r["meta"].get("as_of") or us.get(h, {}).get("written_on") or ""
            out.append({"id": h, "sample": f"calibration_{s}", "label": us.get(h, {}).get("label"), **row(it, as_of)})
    for h, r in json.loads((PROS / "run_60.json").read_text()).items():
        it = r["items"][0]
        if not it.get("card") or not it.get("verification") or "v3" not in it:
            continue
        out.append({"id": h, "sample": "prospective", "label": None, **row(it, r["meta"].get("as_of") or "")})
    return out


def num(k: str, v):
    if v is None:
        return None
    if k in ("N",):
        return nv.LEVELS.index(v)
    if k in ("W", "W_potential"):
        return W_ORDER.index(v)
    return float(v)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    from scipy.stats import spearmanr
    if len(xs) < 5 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    return round(float(spearmanr(xs, ys).statistic), 3)


def auc(rs: list[dict], k: str) -> tuple[float, int] | None:
    pts = [(num(k, r[k]), r["label"]) for r in rs if r["label"] in (0, 1) and r[k] is not None and r["gate"] == "pass"]
    pos, neg = [(v, 0) for v, l in pts if l == 1], [(v, 0) for v, l in pts if l == 0]
    return (round(tied_auc(pos, neg), 3), len(pts)) if pos and neg else None


def main() -> dict:
    rs = units()
    ok = [r for r in rs if r["gate"] == "pass"]
    cal = [r for r in rs if r["sample"].startswith("calibration")]
    out = {"units": len(rs), "passed_gate": len(ok),
           "auc_calibration": {k: auc(cal, k) for k in ("P33", "P34", "ss33", "ss34", "N", "density", "leverage")}}
    sep = {}
    for k in ("N", "density", "leverage", "W_potential", "P34", "ss34"):
        vals = [r[k] for r in ok if r[k] is not None]
        c = Counter(vals if k in ("N", "W_potential") else [round(v, 3) for v in vals])
        top = c.most_common(1)[0][1] / len(vals) if vals else None
        sep[k] = {"known": len(vals), "of": len(ok), "distinct": len(c), "top_share": round(top, 3) if top else None,
                  "levels": dict(c) if k in ("N", "W_potential") else None}
    out["separation"] = sep
    keys = ("P34", "ss34", "against_share", "I", "I_headroom", "W", "feasibility", "N", "density", "leverage", "W_potential")
    rho = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            pr = [(num(a, r[a]), num(b, r[b])) for r in ok if r[a] is not None and r[b] is not None]
            rho[f"{a}~{b}"] = spearman([x for x, _ in pr], [y for _, y in pr])
    out["rho"] = rho
    out["rho_over_0.7"] = {k: v for k, v in rho.items() if v is not None and abs(v) >= 0.7}
    (CAL / "v34_check.json").write_text(json.dumps({"summary": out, "rows": rs}, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

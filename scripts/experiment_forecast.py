"""Forecast from the experiment (specs/experiment-forecast-2026-11-07.yaml): protocol from ClinicalTrials.gov, expected effect
from the records of the outcome slot, power, room for bias -> P(positive). Free; exploration on the calibration.

    python -m scripts.experiment_forecast          # -> $KG_DIR/hypothesis_sources/calibration/experiment_forecast.json
"""
from __future__ import annotations

import json
import math
import statistics

from hyparena.backtest import tied_auc
from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v32 as r32
from hyparena.card.effect_class import _FOLD, _RATIO, _SMD
from scripts.ablation import units
from scripts.ceiling import CAL, design

SHRINK, D_PRIOR, N_UNKNOWN = 0.5, 0.2, 40
ALPHA_CLEAN, ALPHA_OPEN = 0.05, 0.25


def phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def d_of(phrase: str):
    p = (phrase or "").replace("−", "-")
    for rx, kind in ((_RATIO, "ratio"), (_FOLD, "ratio"), (_SMD, "d")):
        m = rx.search(p)
        if m:
            x = float(next(g for g in m.groups() if g).replace(" ", ""))
            if kind == "ratio":
                return abs(math.log(x)) * math.sqrt(3) / math.pi if x > 0 else None
            return abs(x)
    return None


def protocol(nct: str) -> dict:
    p = design(nct) if nct.startswith("NCT") else {}
    d = p.get("designModule", {})
    di = d.get("designInfo", {})
    arms = p.get("armsInterventionsModule", {}).get("armGroups", [])
    types = {a.get("type") for a in arms}
    enr = d.get("enrollmentInfo") or {}
    return {"n": enr.get("count"), "n_type": enr.get("type"), "arms": len(arms) or None,
            "randomised": di.get("allocation") == "RANDOMIZED" if di else None,
            "masking": (di.get("maskingInfo") or {}).get("masking"),
            "placebo_or_sham": bool(types & {"PLACEBO_COMPARATOR", "SHAM_COMPARATOR"}) if arms else None,
            "single_arm": len(arms) == 1 if arms else None,
            "n_primary": len(p.get("outcomesModule", {}).get("primaryOutcomes", [])) if p else None}


def expected_effect(u: dict) -> tuple[float, bool, float]:
    """(d_exp, has a number, S of the outcome slot)."""
    card, cvs = u["card"], u["cvs"]
    e = r32.evaluate(card, cvs, u["alts"], v34=True)
    pre, out = nv.slots(card)
    by = {c.id: c for c in cvs}
    claims = {c.id: c for c in __import__("hyparena.card.rules_v3", fromlist=["x"]).chain(card)}
    num = den = 0.0
    for i in out:
        cv = by.get(i)
        for side, lst in (("for", cv.evidence if cv else []), ("against", cv.counterevidence if cv else [])):
            for r in lst:
                w = r32.record_weight(r, claims[i], side == "against", True)
                if w <= 0:
                    continue
                d = 0.0 if side == "against" else d_of(r.effect_reported)
                if d is None:
                    continue
                num += w * d
                den += w
    S = sum(e.links[i][0] for i in out) / len(out) if out else 0.5
    if den == 0:
        return D_PRIOR, False, S
    return SHRINK * num / den, True, S


def power(d: float, n: int, single: bool) -> float:
    """Single arm: Phi(d sqrt(n) - 1.96); two arms: `n` is twice the per-arm size, Phi(d sqrt(n_per_arm / 2) - 1.96)."""
    if single:
        return phi(d * math.sqrt(n) - 1.96)
    return phi(d * math.sqrt(n / 2 / 2) - 1.96)


def forecast(u: dict, pr: dict, n_override=None) -> dict:
    d, has, S = expected_effect(u)
    n = n_override or pr["n"] or N_UNKNOWN
    arms = max(2, pr["arms"] or 2)
    single = bool(pr["single_arm"])
    pw = power(d, n, True) if single else power(d, n / arms * 2, False)    # n_per_arm = n / arms; power() halves it
    clean = pr["placebo_or_sham"] and pr["masking"] in ("DOUBLE", "TRIPLE", "QUADRUPLE")
    alpha = ALPHA_CLEAN if clean else ALPHA_OPEN
    return {"d_exp": round(d, 3), "d_numeric": has, "pi": round(S, 3), "power": round(pw, 3), "alpha_eff": alpha,
            "forecast": round(S * pw + (1 - S) * alpha, 4)}


def auc(rows, key):
    pts = [(r[key], r["label"]) for r in rows if r.get(key) is not None]
    pos, neg = [(v, 0) for v, l in pts if l == 1], [(v, 0) for v, l in pts if l == 0]
    return (round(tied_auc(pos, neg), 3), len(pts)) if pos and neg else None


def main() -> dict:
    us = units()
    rows = []
    for u in us:
        pr = protocol(u["id"])
        f = forecast(u, pr)
        rows.append({"id": u["id"], "label": u["label"], **pr, **f})
    ns = [r["n"] for r in rows if r["n"]]
    med = int(statistics.median(ns)) if ns else N_UNKNOWN
    for r, u in zip(rows, us):
        r["forecast_median_n"] = forecast(u, protocol(u["id"]), n_override=med)["forecast"]
    v34 = {r["id"]: r for r in json.loads((CAL / "v34_check.json").read_text())["rows"]}
    cons = {r["id"]: r for r in json.loads((CAL / "llm_consensus_summary.json").read_text())["rows"]}
    for r in rows:
        r["P34"] = (v34.get(r["id"]) or {}).get("P34")
        r["models"] = (cons.get(r["id"]) or {}).get("prob")
        r["log_n"] = math.log(r["n"]) if r["n"] else None
    out = {"n": len(rows), "with_numeric_effect": sum(r["d_numeric"] for r in rows), "median_enrollment": med,
           "auc": {k: auc(rows, k) for k in ("forecast", "forecast_median_n", "power", "pi", "alpha_eff", "d_exp", "log_n", "P34", "models")}}
    (CAL / "experiment_forecast.json").write_text(json.dumps({"summary": out, "rows": rows}, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

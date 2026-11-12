# Data note (2026-11-12): the raw calibration runs of methods v2 and v3 before normaliser v10 (run_{s}_v3.json, run_{s}_msearch.json,
# run_1.json) were removed from longevity-kg; the numbers are in the spec named below. Restore them from the git history to re-run.
"""The check of specs/trend-genetics-2026-11-06.yaml on saved runs (no model calls).

    python -m scripts.trend_genetics_check          # writes $KG_DIR/hypothesis_sources/calibration/trend_genetics.json
"""
from __future__ import annotations

import json
import math
from collections import Counter

from scipy.stats import spearmanr

from hyparena.backtest import tied_auc
from hyparena.card import rules_v32, trend_genetics as tg, v3_extra
from hyparena.card.models import ClaimVerification, HypothesisCard
from scripts.ctgov_outcomes import KG

CAL = KG / "hypothesis_sources" / "calibration"
PRO = KG / "hypothesis_sources" / "prospective"
EP = {"biomarker": 0, "patient_reported": 1, "function": 2, "clinical_event": 3}
SCOPE = {"local": 0, "organ": 1, "hallmark": 2, "systemic": 2}


def units() -> list[tuple[str, str, dict, dict, object]]:
    """(sample, unit id, run result, unit, endpoint) for every unit with a v3 result."""
    out = []
    est = json.loads((CAL / "estimand_v1.json").read_text())
    for s in (1, 2, 3, 4, 5):
        us = {u["id"]: u for u in json.loads((CAL / f"units_{s}.json").read_text())}
        for h, r in json.loads((CAL / f"run_{s}_v3.json").read_text()).items():
            if h in us:
                v = {est.get(f"{h}|{f}", {}).get("clean", {}).get("endpoint") for f in ("google", "deepseek")}
                out.append(("calibration" if s <= 3 else "fresh", h, r, us[h], v.pop() if len(v) == 1 else None))
    from scripts.prospective import endpoint_clinical
    for h, r in json.loads((PRO / "run_60.json").read_text()).items():
        out.append(("prospective", h, r, {"id": h}, endpoint_clinical(60, h)))
    return out


def main() -> dict:
    rows = {}
    for sample, h, r, u, ep in units():
        it = r["items"][0]
        if not it.get("card") or not it.get("verification") or "v3" not in it:
            continue
        card = HypothesisCard.model_validate(it["card"])
        cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
        alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
        as_of = r["meta"].get("as_of") or "2026-11-06"
        e = rules_v32.evaluate(card, cvs, alts, fold=True)
        ext = v3_extra.extras(card, cvs, it["v3"], as_of)
        tp, q = tg.trend_pubmed(card, as_of)
        gs, genes = tg.genetic_support(card)
        rows[h] = {"sample": sample, "as_of": as_of, "label": u.get("label"), "trend_pubmed": tp, "query": q,
                   "trend_trials": tg.trend_trials(card, as_of), "genetic_support": gs, "genes": genes,
                   "P": e.P, "I": e.I, "scope": SCOPE.get(e.scope, 0), "feasibility": ext["feasibility"],
                   "momentum": ext["momentum"], "endpoint": EP.get(ep) if ep else None,
                   "intervention": [i.label for i in card.pico.intervention][:1]}
    (CAL / "trend_genetics.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    n = len(rows)
    out = {"units": n, "by_sample": dict(Counter(x["sample"] for x in rows.values()))}
    for ind in ("trend_pubmed", "trend_trials"):
        vals = [x[ind] for x in rows.values() if x[ind] is not None]
        top = Counter(round(v, 2) for v in vals).most_common(1)
        out[ind] = {"known": len(vals), "share_known": round(len(vals) / n, 2), "distinct": len({round(v, 3) for v in vals}),
                    "top_share": round(top[0][1] / len(vals), 2) if vals else None,
                    "median": round(sorted(vals)[len(vals) // 2], 3) if vals else None}
    gl = [x["genetic_support"] for x in rows.values() if x["genetic_support"]]
    out["genetic_support"] = {"known": len(gl), "share_known": round(len(gl) / n, 2), "levels": dict(Counter(gl))}
    num = {"trend_pubmed": lambda x: x["trend_pubmed"], "trend_trials": lambda x: x["trend_trials"],
           "genetic_support": lambda x: tg.GENETIC_LEVELS.index(x["genetic_support"]) if x["genetic_support"] else None}
    out["non_redundancy"] = {}
    for ind, f in num.items():
        res = {}
        for ax in ("P", "I", "scope", "feasibility", "momentum", "endpoint", "trend_pubmed"):
            if ax == ind:
                continue
            pairs = [(f(x), x[ax]) for x in rows.values() if f(x) is not None and x[ax] is not None]
            if len(pairs) >= 8 and len({p for p, _ in pairs}) > 1 and len({q for _, q in pairs}) > 1:
                res[ax] = [round(float(spearmanr([p for p, _ in pairs], [q for _, q in pairs]).correlation), 2), len(pairs)]
        out["non_redundancy"][ind] = res
    out["orientation_auc"] = {}
    for ind, f in num.items():
        lab = [(f(x), x["label"]) for x in rows.values() if x["label"] in (0, 1) and f(x) is not None]
        if lab and {l for _, l in lab} == {0, 1}:
            out["orientation_auc"][ind] = [round(tied_auc([(v, 0) for v, l in lab if l == 1], [(v, 0) for v, l in lab if l == 0]), 3),
                                           sum(l for _, l in lab), sum(1 - l for _, l in lab)]
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

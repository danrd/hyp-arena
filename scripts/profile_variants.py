"""Alternative tier orders of the ASPID profiles (user requests 2026-11-09: frontier sets; W higher in funding). Free.

    python -m scripts.profile_variants     # -> calibration/profile_variants.json

Per variant: on the prospective pool (v3.6, judged d) Spearman of the expected score with the current profile and overlap of
the top 10; on the calibration pool the tied AUC against trial outcomes (R3, a constraint only); the share of the score's
spread each tier gets is set by ASPID's order, so the variants differ only in order.
"""
from __future__ import annotations

import datetime as dt
import json

from scipy.stats import spearmanr

from hyparena.card import alternatives_d, aspid_v3, rules_v32, v3_extra
from hyparena.card import novelty_v34 as nv
from hyparena.card import trend_genetics as tg
from hyparena.card.models import ClaimVerification, HypothesisCard
from scripts.ablation import auc_of
from scripts.v34_check import CAL, PROS

VARIANTS = {
    "frontier": {
        "current: N > balance > {I, feasibility}": [["N"], ["chain_state"], ["I", "feasibility"]],
        "N > balance > I > feasibility": [["N"], ["chain_state"], ["I"], ["feasibility"]],
        "N > balance > {I, feasibility} > W": [["N"], ["chain_state"], ["I", "feasibility"], ["W"]],
        "N > balance > I > feasibility > W": [["N"], ["chain_state"], ["I"], ["feasibility"], ["W"]],
        "N > balance > {I, W} > feasibility": [["N"], ["chain_state"], ["I", "W"], ["feasibility"]],
        "N > {balance, I} > feasibility": [["N"], ["chain_state", "I"], ["feasibility"]],
        "{N, balance} > I > feasibility": [["N", "chain_state"], ["I"], ["feasibility"]],
        "N > I > balance > feasibility": [["N"], ["I"], ["chain_state"], ["feasibility"]],
    },
    "funding": {
        "current: W in tier 5": [["chain_state"], ["feasibility"], ["trend_pubmed", "ai_role", "N"], ["I"],
                                 ["W", "endpoint_clinical", "best_design_outcome", "independent_outcome"]],
        "W +1: {I, W} in tier 4": [["chain_state"], ["feasibility"], ["trend_pubmed", "ai_role", "N"], ["I", "W"],
                                   ["endpoint_clinical", "best_design_outcome", "independent_outcome"]],
        "W +1.5: W alone above I": [["chain_state"], ["feasibility"], ["trend_pubmed", "ai_role", "N"], ["W"], ["I"],
                                    ["endpoint_clinical", "best_design_outcome", "independent_outcome"]],
        "W +2: {trend, AI, N, W} in tier 3": [["chain_state"], ["feasibility"], ["trend_pubmed", "ai_role", "N", "W"], ["I"],
                                              ["endpoint_clinical", "best_design_outcome", "independent_outcome"]],
    },
}


def _ax(card, cvs, alts, v3, as_of, endpoint):
    e = rules_v32.evaluate(card, cvs, alts, v36=True)
    if e.gate != "pass":
        return None
    ext = v3_extra.extras(card, cvs, v3, as_of)
    ext.update({"support_share": e.support_share, "chain_state": e.chain_state, "N": nv.novelty(card, cvs, e),
                "endpoint_clinical": endpoint, "ai_role": card.ai_role,
                "trend_pubmed": tg.trend_pubmed(card, as_of or dt.date.today().isoformat())[0]})
    return {"P": e.P, "scope": e.scope, "I": e.I, "headroom_I": e.headroom_I, "gate": e.gate}, ext


def prospective():
    from scripts.prospective import endpoint_clinical
    out = {}
    for h, r in json.loads((PROS / "run_60.json").read_text()).items():
        it = r["items"][0]
        if not it.get("card") or not it.get("verification") or "v3" not in it:
            continue
        card = alternatives_d.apply(h, HypothesisCard.model_validate(it["card"]))
        cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
        alts = {k: ClaimVerification.model_validate(v) for k, v in (it.get("v3_alternatives") or {}).items()}
        a = _ax(card, cvs, alts, it["v3"], r["meta"].get("as_of") or "", endpoint_clinical(60, h))
        if a:
            out[h] = a
    return out


def calibration():
    from scripts.ablation import endpoint, units
    ax, label, filtered = {}, {}, []
    for u in units():
        ep = endpoint(u["id"])
        ep = None if ep is None else ("biomarker", "patient_reported", "function", "clinical_event")[int(ep)]
        a = _ax(u["card"], u["cvs"], u["alts"], u["v3"], u["as_of"], ep)
        if a:
            ax[u["id"]], label[u["id"]] = a, u["label"]
        else:
            filtered.append((-1.0, u["label"]))
    return ax, label, filtered


def expected(ax, name, tiers, K=4000):
    ids = [k for t in tiers for k in t]
    prof = aspid_v3.Profile(name=name, version="variant", tiers=tiers, description="")
    vals = {h: {k: aspid_v3.values_of(v3, ext)[k] for k in ids} for h, (v3, ext) in ax.items()}
    return aspid_v3.aggregate(vals, [aspid_v3.SPECS[k] for k in ids], prof, K=K, seed=0).expected


def main() -> dict:
    pa = prospective()
    ca, label, filtered = calibration()
    out = {"prospective_units": len(pa), "calibration_units": len(ca) + len(filtered)}
    for prof, vs in VARIANTS.items():
        base = None
        rows = {}
        for vname, tiers in vs.items():
            ep = expected(pa, prof, tiers)
            if base is None:
                base = ep
            hs = sorted(ep)
            top = lambda d: set(sorted(d, key=lambda h: -d[h])[:10])
            ec = expected(ca, prof, tiers)
            rows[vname] = {"spearman_with_current": round(float(spearmanr([ep[h] for h in hs], [base[h] for h in hs]).statistic), 3),
                           "top10_kept": len(top(ep) & top(base)),
                           "auc_calibration": auc_of([(ec[h], label[h]) for h in ec] + filtered)}
        out[prof] = rows
    (CAL / "profile_variants.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

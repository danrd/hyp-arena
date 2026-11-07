"""Ablation on the calibration (free, no model calls): which parts of the method carry the signal against trial outcomes and
which are dead weight (user request 2026-11-07).

    python -m scripts.ablation        # writes $KG_DIR/hypothesis_sources/calibration/ablation.json

A. P (v3.4) with one factor of the record weight set to 1 (design, precision, effect, comparison, context), without the fold,
   without the v3.4 changes, and simpler variants (the outcome link alone; support only).
B. The ASPID score of each profile with all its indicators and with each indicator dropped (the others keep their order).
Exploration only: the samples built the method; with 72 units an AUC moves by about 0.065 by chance (one standard error).
"""
from __future__ import annotations

import json
from contextlib import contextmanager

from hyparena.backtest import tied_auc
from hyparena.card import aspid_v3
from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card import trend_genetics as tg
from hyparena.card import v3_extra
from hyparena.card import v3_levels as lv
from hyparena.card.models import ClaimVerification, HypothesisCard
from scripts.ceiling import CAL, endpoint

FACTORS = ("design", "precision", "effect", "comparison", "context")
_orig = r32.record_weight


def _weight(drop: set[str]):
    def rw(rec, claim, against, v34=False):
        if not r3.usable(rec, r32.VARIANT_BASE):
            return 0.0
        ctx = r32.context_v34(rec, claim) if v34 else r3.context_level(rec)
        if ctx is None:
            return 0.0
        pre = claim.link in r3.PRECLINICAL_LINKS
        w = 1.0
        if "design" not in drop:
            w *= lv.design_weight(r3.record_design(rec), r3.human_claim(claim) and not pre)
        if "precision" not in drop:
            w *= r32.PRECLINICAL_PRECISION if (v34 and pre) else r32.precision(rec.n_total)
        if "effect" not in drop:
            w *= r32.effect_weight(rec, against)
        if "comparison" not in drop:
            w *= lv.weight("comparison", rec.comparison if rec.comparison != "unknown" else "none")
        if "context" not in drop:
            w *= lv.weight("context", ctx)
        return w
    return rw


@contextmanager
def dropped(drop: set[str]):
    r32.record_weight = _weight(drop)
    try:
        yield
    finally:
        r32.record_weight = _orig


def units() -> list[dict]:
    out = []
    for s in (1, 2, 3, 4, 5):
        us = {u["id"]: u for u in json.loads((CAL / f"units_{s}.json").read_text())}
        for h, r in json.loads((CAL / f"run_{s}_v10.json").read_text()).items():
            it = r["items"][0]
            if us.get(h, {}).get("label") not in (0, 1) or not it.get("card") or not it.get("verification") or "v3" not in it:
                continue
            card = HypothesisCard.model_validate(it["card"])
            cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
            alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
            out.append({"id": h, "label": us[h]["label"], "card": card, "cvs": cvs, "alts": alts, "v3": it["v3"],
                        "as_of": r["meta"].get("as_of") or us[h].get("written_on") or ""})
    return out


def auc_of(vals: list[tuple[float, int]]) -> float | None:
    pos, neg = [(v, 0) for v, l in vals if l == 1], [(v, 0) for v, l in vals if l == 0]
    return round(tied_auc(pos, neg), 3) if pos and neg else None


def p_auc(us, **kw) -> float | None:
    vals = []
    for u in us:
        e = r32.evaluate(u["card"], u["cvs"], u["alts"], **kw)
        vals.append((-1.0 if e.gate != "pass" else e.P, u["label"]))
    return auc_of(vals)


def outcome_S(u, **kw) -> float:
    e = r32.evaluate(u["card"], u["cvs"], u["alts"], **kw)
    pre, out = nv.slots(u["card"])
    return sum(e.links[i][0] for i in out) / len(out) if out else 0.5


def part_a(us) -> dict:
    res = {"P v3.4 (all)": p_auc(us, v34=True), "P v3.3": p_auc(us, fold=True, neutral_unverified=True),
           "P v3.4 without fold (not possible: v3.4 forces it), v3.3 without fold": p_auc(us, neutral_unverified=True)}
    for f in FACTORS:
        with dropped({f}):
            res[f"P v3.4 without {f}"] = p_auc(us, v34=True)
    with dropped(set(FACTORS)):
        res["P v3.4, every record weight 1 (counts only)"] = p_auc(us, v34=True)
    res["outcome link S alone (v3.4 weights)"] = auc_of([(outcome_S(u, v34=True), u["label"]) for u in us])
    for f in FACTORS:
        with dropped({f}):
            res[f"outcome link S without {f}"] = auc_of([(outcome_S(u, v34=True), u["label"]) for u in us])
    res["support share (v3.4)"] = auc_of([(r32.evaluate(u["card"], u["cvs"], u["alts"], v34=True).support_share, u["label"]) for u in us])
    return res


def indicators(us) -> dict[str, tuple[dict, dict]]:
    ax = {}
    for u in us:
        e = r32.evaluate(u["card"], u["cvs"], u["alts"], v34=True)
        if e.gate != "pass":
            continue
        ext = v3_extra.extras(u["card"], u["cvs"], u["v3"], u["as_of"])
        ext.update({"support_share": e.support_share, "N": nv.novelty(u["card"], u["cvs"], e), "ai_role": u["card"].ai_role,
                    "trend_pubmed": tg.trend_pubmed(u["card"], u["as_of"])[0], "endpoint_clinical": None})
        ep = endpoint(u["id"])
        ext["endpoint_clinical"] = None if ep is None else ("biomarker", "patient_reported", "function", "clinical_event")[int(ep)]
        ax[u["id"]] = ({"P": e.P, "scope": e.scope, "I": e.I, "headroom_I": u["v3"].get("headroom_I"), "gate": "pass"}, ext)
    return ax


def part_b(us) -> dict:
    ax = indicators(us)
    label = {u["id"]: u["label"] for u in us}
    filtered = [(-1.0, u["label"]) for u in us if u["id"] not in ax]
    profiles = aspid_v3.load()
    out = {}
    for name, (prof, ids) in profiles.items():
        def score(tiers):
            p2 = aspid_v3.Profile(name=name, version="ablation", tiers=tiers, description="")
            specs = [aspid_v3.SPECS[k] for t in tiers for k in t]
            vals = {h: {k: aspid_v3.values_of(v3, ext)[k] for t in tiers for k in t} for h, (v3, ext) in ax.items()}
            agg = aspid_v3.aggregate(vals, specs, p2, K=3000, seed=0)
            return auc_of([(agg.expected[h], label[h]) for h in ax] + filtered)
        row = {"all": score(prof.tiers)}
        for k in ids:
            tiers = [[x for x in t if x != k] for t in prof.tiers]
            tiers = [t for t in tiers if t]
            row[f"without {k}"] = score(tiers) if tiers else None
        out[name] = row
    return out


def main() -> dict:
    us = units()
    out = {"n": len(us), "positives": sum(u["label"] for u in us), "A_P_and_record_weight": part_a(us),
           "B_profiles": part_b(us)}
    (CAL / "ablation.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

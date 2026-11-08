"""I on the calibration with the d judged from the registry text vs the proposer's d (specs/informativeness-check-2026-11-08.yaml,
item 3 of 2026-11-08). Free. Exploration: the 73 units built the method; an AUC moves by about 0.065 by chance.

    python -m scripts.i_recalibration      # -> calibration/i_recalibration.json
"""
from __future__ import annotations

import json

from hyparena.card import alternatives_d
from hyparena.card import aspid_v3
from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v32 as r32
from hyparena.card import trend_genetics as tg
from hyparena.card import v3_extra
from scripts.ablation import auc_of, units
from scripts.ceiling import CAL, endpoint


def axes(us):
    ax = {}
    for u in us:
        e = r32.evaluate(u["card"], u["cvs"], u["alts"], v36=True)
        if e.gate != "pass":
            continue
        ext = v3_extra.extras(u["card"], u["cvs"], u["v3"], u["as_of"])
        ep = endpoint(u["id"])
        with r32.method():
            N = nv.novelty(u["card"], u["cvs"], e)
        ext.update({"support_share": e.support_share, "chain_state": e.chain_state, "N": N, "ai_role": u["card"].ai_role,
                    "trend_pubmed": tg.trend_pubmed(u["card"], u["as_of"])[0],
                    "endpoint_clinical": None if ep is None else ("biomarker", "patient_reported", "function", "clinical_event")[int(ep)]})
        ax[u["id"]] = ({"P": e.P, "scope": e.scope, "I": e.I, "headroom_I": e.headroom_I, "gate": "pass"}, ext)
    return ax


def measure(us) -> dict:
    ax = axes(us)
    label = {u["id"]: u["label"] for u in us}
    filtered = [(-1.0, u["label"]) for u in us if u["id"] not in ax]
    out = {"I_auc": auc_of([(v3["I"], label[h]) for h, (v3, _) in ax.items()] + [(0.0, l) for _, l in filtered]),
           "I_positive_share": round(sum(v3["I"] > 0 for v3, _ in ax.values()) / len(ax), 3),
           "I_mean": round(sum(v3["I"] for v3, _ in ax.values()) / len(ax), 3)}
    for name, (prof, ids) in aspid_v3.load().items():
        def score(tiers):
            p2 = aspid_v3.Profile(name=name, version="recal", tiers=tiers, description="")
            specs = [aspid_v3.SPECS[k] for t in tiers for k in t]
            vals = {h: {k: aspid_v3.values_of(v3, ext)[k] for t in tiers for k in t} for h, (v3, ext) in ax.items()}
            agg = aspid_v3.aggregate(vals, specs, p2, K=3000, seed=0)
            return auc_of([(agg.expected[h], label[h]) for h in ax] + filtered)
        no_i = [t for t in ([x for x in t if x != "I"] for t in prof.tiers) if t]
        out[name] = {"all": score(prof.tiers), "without_I": score(no_i)}
    return out


def main() -> dict:
    alternatives_d.ENABLED = False
    before = measure(units())
    alternatives_d.ENABLED = True
    after = measure(units())
    out = {"proposer_d": before, "judged_d": after}
    (CAL / "i_recalibration.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))

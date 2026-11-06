"""Estimand check (specs/estimand-2026-11-06.yaml): five ICH E9(R1) attributes from the registry texts by two model families,
then the four admission conditions for an indicator.

    ALLOW_PAID=1 python -m scripts.estimand_check run      # 74 texts x 2 families
    python -m scripts.estimand_check score                 # no calls
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

from scripts.ctgov_outcomes import KG

CAL = KG / "hypothesis_sources" / "calibration"
OUT = CAL / "estimand_v1.json"
ATTRS = {"population": ("healthy_older", "older_with_condition", "other"),
         "intervention": ("specified", "named_only"),
         "endpoint": ("clinical_event", "function", "patient_reported", "biomarker"),
         "summary_measure": ("difference_in_means", "ratio_or_proportion", "time_to_event"),
         "intercurrent_events": ("treatment_policy", "hypothetical", "composite", "while_on_treatment", "principal_stratum")}
FAMILIES = ("google", "deepseek")


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def clean(value: dict, text: str) -> dict:
    """Allowed values with a verbatim phrase; anything else not_stated."""
    e = (value or {}).get("estimand") or {}
    out = {}
    for a, allowed in ATTRS.items():
        v = e.get(a) or {}
        val, q = v.get("value"), (v.get("quote") or "").strip()
        out[a] = val if val in allowed and q and _norm(q) in _norm(text) else "not_stated"
    return out


def problems(value: dict) -> list[str]:
    e = (value or {}).get("estimand")
    if not isinstance(e, dict):
        return ["no estimand object"]
    return [f"{a}: value must be one of {list(v) + ['not_stated']}" for a, v in ATTRS.items()
            if (e.get(a) or {}).get("value") not in (*v, "not_stated")]


def texts() -> list[dict]:
    out = []
    for s in (1, 2, 3, 4, 5):
        out += [dict(json.loads(l), step=s) for l in open(CAL / f"texts_{s}.jsonl")]
    return out


def run() -> None:
    from hyparena.card.llm import ask
    from hyparena.llm.providers import build_client
    client, _, _ = build_client("configs/v3-flash.yaml", max_calls=200)
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    for t in texts():
        for fam in FAMILIES:
            key = f"{t['id']}|{fam}"
            if key in done:
                continue
            log: list = []
            value, got = ask(client, role="verify_claim", family=fam, template="estimand", version="v1", variables={"text": t["text"]},
                             validate=problems, rounds=2, log=log)
            done[key] = {"family_asked": fam, "family": got, "raw": value, "clean": clean(value, t["text"]),
                         "calls": len(log), "tokens": sum((x.get("tokens_in") or 0) + (x.get("tokens_out") or 0) for x in log)}
            OUT.write_text(json.dumps(done, indent=1, ensure_ascii=False))
            print(key, done[key]["clean"], flush=True)


def kappa(a: list, b: list, weights=None) -> float:
    from sklearn.metrics import cohen_kappa_score
    if len(set(a) | set(b)) < 2:
        return float("nan")
    return float(cohen_kappa_score(a, b, weights=weights))


def score() -> dict:
    from scipy.stats import spearmanr
    from hyparena.backtest import tied_auc
    from hyparena.card import rules_v32
    from hyparena.card.models import ClaimVerification, HypothesisCard
    d = json.loads(OUT.read_text())
    ts = texts()
    ids = [t["id"] for t in ts if all(f"{t['id']}|{f}" in d for f in FAMILIES)]
    g = {h: d[f"{h}|google"]["clean"] for h in ids}
    k = {h: d[f"{h}|deepseek"]["clean"] for h in ids}
    comp = lambda c: sum(v != "not_stated" for v in c.values())
    out = {"texts": len(ids), "families_answered": dict(Counter(d[x]["family"] for x in d)), "attributes": {}}
    for a in ATTRS:
        x, y = [g[h][a] for h in ids], [k[h][a] for h in ids]
        dist = Counter(x)
        out["attributes"][a] = {"kappa": round(kappa(x, y), 2), "agreement": round(sum(p == q for p, q in zip(x, y)) / len(ids), 2),
                                "values_google": dict(dist), "top_share": round(dist.most_common(1)[0][1] / len(ids), 2)}
    cx, cy = [comp(g[h]) for h in ids], [comp(k[h]) for h in ids]
    dist = Counter(cx)
    out["completeness"] = {"weighted_kappa": round(kappa(cx, cy, "linear"), 2), "values_google": dict(sorted(dist.items())),
                           "top_share": round(dist.most_common(1)[0][1] / len(ids), 2)}
    # non-redundancy and orientation on scored units
    us, sc = {}, {}
    for s in (1, 2, 3, 4, 5):
        us.update({u["id"]: u for u in json.loads((CAL / f"units_{s}.json").read_text())})
        for h, r in json.loads((CAL / f"run_{s}_v3.json").read_text()).items():
            it = r["items"][0]
            if h not in ids or not it.get("card") or not it.get("verification") or "v3" not in it:
                continue
            card = HypothesisCard.model_validate(it["card"])
            cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
            alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
            e = rules_v32.evaluate(card, cvs, alts, fold=True)
            sc[h] = {"P": e.P, "I": e.I, "scope": {"local": 0, "hallmark": 1, "systemic": 2}.get(e.scope, 0)}
    hs = sorted(sc)
    ep_rank = {"biomarker": 0, "patient_reported": 1, "function": 2, "clinical_event": 3, "not_stated": -1}
    cand = {"completeness": {h: comp(g[h]) for h in hs}, "endpoint_ordinal": {h: ep_rank[g[h]["endpoint"]] for h in hs}}
    out["non_redundancy"] = {c: {ax: round(float(spearmanr([v[h] for h in hs], [sc[h][ax] for h in hs]).correlation), 2)
                                 for ax in ("P", "I", "scope")} for c, v in cand.items()}
    lab = {h: us[h].get("label") for h in hs if us[h].get("label") in (0, 1)}
    out["orientation_auc"] = {c: round(tied_auc([(v[h], 0) for h in lab if lab[h] == 1], [(v[h], 0) for h in lab if lab[h] == 0]), 3)
                              for c, v in cand.items()}
    out["orientation_units"] = {"pos": sum(v == 1 for v in lab.values()), "neg": sum(v == 0 for v in lab.values())}
    out["cost"] = {"calls": sum(x["calls"] for x in d.values()), "tokens": sum(x["tokens"] for x in d.values())}
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        if os.environ.get("ALLOW_PAID") != "1":
            raise SystemExit("paid: set ALLOW_PAID=1")
        run()
    elif cmd == "score":
        print(json.dumps(score(), indent=1, ensure_ascii=False))
    else:
        raise SystemExit(__doc__)

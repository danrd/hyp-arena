"""Error analysis of P (v3.2, fold) on the calibration samples (steps 1-5), no model calls (specs/error-analysis-2026-11-06.yaml).

    python -m scripts.error_analysis          # writes $KG_DIR/hypothesis_sources/calibration/error_analysis.json

Three questions, exploration only (the samples were used to build the method, nothing here is a test):
1. baselines: does a simple number order the trials as well as P (planned n, literature volume on the intervention before T,
   number of usable records found, trend of attention)?
2. ablation: does the mechanism add anything to the outcome link (P vs the strength of the outcome link alone)?
3. errors: positives with a low P and nulls with a high P, each with its likely cause read off the saved run.
"""
from __future__ import annotations

import json
import math
from collections import Counter

from hyparena.backtest import tied_auc
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card import trend_genetics as tg
from hyparena.card.models import ClaimVerification, HypothesisCard
from scripts.ctgov_outcomes import KG

CAL = KG / "hypothesis_sources" / "calibration"


def literature_volume(card: HypothesisCard, as_of: str) -> int | None:
    for q in tg.terms(card):
        n = tg.pubmed_count(q, "1900-01-01", tg._windows(as_of)[0][1])
        if n >= 5:
            return n
    return None


def rows() -> list[dict]:
    out = []
    for s in (1, 2, 3, 4, 5):
        us = {u["id"]: u for u in json.loads((CAL / f"units_{s}.json").read_text())}
        texts = {json.loads(l)["id"]: json.loads(l)["text"] for l in open(CAL / f"texts_{s}.jsonl")}
        for h, r in json.loads((CAL / f"run_{s}_v3.json").read_text()).items():
            if h not in us or us[h].get("label") not in (0, 1):
                continue
            it = r["items"][0]
            title = next((l[6:].strip() for l in texts.get(h, "").splitlines() if l.startswith("Title:")), "")
            row = {"id": h, "step": s, "label": us[h]["label"], "type": us[h].get("type"), "title": title,
                   "outcome": it["outcome"]}
            if not it.get("card") or not it.get("verification") or "v3" not in it:
                row["P"] = None
                out.append(row)
                continue
            card = HypothesisCard.model_validate(it["card"])
            cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
            alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
            e = r32.evaluate(card, cvs, alts, fold=True)
            links = r3.chain(card)
            outs, primary = r3.outcome_group(card, links)
            out_ids = [primary.id] if primary is not None else [o.id for o in outs]
            S_out = sum(e.links[i][0] for i in out_ids) / len(out_ids) if out_ids else 0.5
            by = {c.id: c for c in cvs}
            usable = {i: sum(1 for rec in (by[i].evidence + by[i].counterevidence if i in by else [])
                             if r32.record_weight(rec, next(c for c in links if c.id == i), False) > 0) for i in e.links}
            no_stance = sum(len(c.no_stance) for c in cvs)
            as_of = r["meta"].get("as_of") or us[h]["written_on"]
            row.update({
                "P": -1.0 if e.gate == "filtered" else e.P, "gate": e.gate, "S_outcome": S_out, "links": len(links),
                "mechanism": any(c.link != "outcome" for c in links), "records_outcome": sum(usable[i] for i in out_ids),
                "records_total": sum(usable.values()), "no_stance": no_stance,
                "F_out": sum(e.links[i][3] for i in out_ids), "A_out": sum(e.links[i][4] for i in out_ids),
                "n_planned": card.decisive_experiment.n_planned, "intervention": [i.label for i in card.pico.intervention][:1],
                "plain": card.claim_plain, "lit_volume": literature_volume(card, as_of),
                "trend": tg.trend_pubmed(card, as_of)[0], "I": e.I,
            })
            out.append(row)
    return out


def auc(rs: list[dict], key, sign: float = 1.0) -> tuple[float, int] | None:
    pts = [(sign * k, r["label"]) for r in rs if (k := key(r)) is not None]
    pos, neg = [(v, 0) for v, l in pts if l == 1], [(v, 0) for v, l in pts if l == 0]
    if not pos or not neg:
        return None
    return round(tied_auc(pos, neg), 3), len(pts)


def cause(r: dict, median_P: float) -> list[str]:
    c = []
    if r["label"] == 1:
        if not r["mechanism"]:
            c.append("no mechanism written: P is the outcome link alone")
        if r["records_outcome"] == 0:
            c.append("no usable record on the outcome link (S 0.5)" + (f"; {r['no_stance']} papers read without a stance" if r["no_stance"] else ""))
        if r["A_out"] > 0:
            c.append(f"records against on the outcome (A {r['A_out']:.2f} vs F {r['F_out']:.2f})")
        if r["links"] >= 3 and r["S_outcome"] >= 0.75:
            c.append("outcome supported but a long chain with unverified links multiplies P down")
    else:
        if r["S_outcome"] >= 0.75:
            c.append(f"strong prior support for the outcome (F {r['F_out']:.2f}), the trial was null anyway")
        if r["records_outcome"] == 0 and r["P"] >= median_P:
            c.append("high P without outcome records: carried by a short chain at 0.5")
    return c or ["unclear from the saved run"]


def main() -> dict:
    rs = rows()
    sc = [r for r in rs if r.get("P") is not None]
    med = sorted(r["P"] for r in sc)[len(sc) // 2]
    out = {"units": len(rs), "scored": len(sc), "labels": dict(Counter(r["label"] for r in sc)), "median_P": round(med, 3)}
    out["auc"] = {
        "P (v3.2 fold)": auc(sc, lambda r: r["P"]),
        "outcome link alone (S_outcome)": auc(sc, lambda r: r["S_outcome"]),
        "F of the outcome link": auc(sc, lambda r: r["F_out"]),
        "usable records on the outcome": auc(sc, lambda r: r["records_outcome"]),
        "usable records, whole chain": auc(sc, lambda r: r["records_total"]),
        "literature volume on the intervention (log)": auc(sc, lambda r: math.log(r["lit_volume"]) if r["lit_volume"] else None),
        "planned n (log)": auc(sc, lambda r: math.log(r["n_planned"]) if r["n_planned"] else None),
        "trend of attention": auc(sc, lambda r: r["trend"]),
        "I": auc(sc, lambda r: r["I"]),
        "mechanism written (0/1)": auc(sc, lambda r: 1.0 if r["mechanism"] else 0.0),
    }
    by_mech = {}
    for m in (True, False):
        sub = [r for r in sc if r["mechanism"] == m]
        by_mech["with mechanism" if m else "outcome only"] = {"n": len(sub), "pos": sum(r["label"] for r in sub), "P_auc": auc(sub, lambda r: r["P"])}
    out["by_mechanism"] = by_mech
    by_type = {}
    for ty in sorted({r["type"] for r in sc if r["type"]}):
        sub = [r for r in sc if r["type"] == ty]
        by_type[ty] = {"n": len(sub), "pos": sum(r["label"] for r in sub), "P_auc": auc(sub, lambda r: r["P"]),
                       "mean_P": round(sum(r["P"] for r in sub) / len(sub), 3)}
    out["by_type"] = by_type
    errors = []
    for r in sc:
        low_pos = r["label"] == 1 and r["P"] < med
        high_neg = r["label"] == 0 and r["P"] >= med
        if low_pos or high_neg:
            errors.append({"id": r["id"], "kind": "positive, low P" if low_pos else "null, high P", "P": round(r["P"], 3),
                           "S_outcome": round(r["S_outcome"], 3), "records_outcome": r["records_outcome"], "links": r["links"],
                           "title": r["title"][:110], "intervention": r["intervention"], "causes": cause(r, med)})
    out["errors"] = errors
    out["error_causes"] = dict(Counter(c.split(":")[0].split(" (")[0].split(";")[0] for e in errors for c in e["causes"]))
    out["unscored"] = [{"id": r["id"], "label": r["label"], "outcome": r["outcome"]} for r in rs if r.get("P") is None]
    (CAL / "error_analysis.json").write_text(json.dumps({"summary": out, "rows": rs}, indent=1, ensure_ascii=False, default=str) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

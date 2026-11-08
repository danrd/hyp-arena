"""Compare arms of the sources experiment (specs/sources-experiment-2026-11-07.yaml) on the 15 units, free:
old abstracts (v9, saved calibration runs), arm A (v10 + exact-population query), arm B (full texts, when run), Argon's graph.

    python -m scripts.sources_compare        # -> calibration/sources_compare.json

Reference for recall: the union of every arm's link-paper pairs that passed the checks (Argon's graph after the re-check).
Field accuracy: against Argon's labels (pack 3, task D) and graph edges for the same link and paper.
"""
from __future__ import annotations

import json
from collections import Counter

from hyparena.backtest import tied_auc
from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.effect_class import d_from_ci, from_phrase
from hyparena.card.models import ClaimVerification, HypothesisCard
from scripts.argon_check import SRC, check_quotes
from scripts.experiment_forecast import d_of
from scripts.ablation import units
from scripts.ceiling import CAL


def has_number(r) -> bool:
    p = r.effect_reported or ""
    return d_of(p) is not None or d_from_ci(p, r.n_total, r.comparison) is not None or from_phrase(p) != "unclear"


def arm_parts(item: dict):
    card = HypothesisCard.model_validate(item["card"])
    cvs = [ClaimVerification.model_validate(c) for c in item["verification"]["claims"]]
    alts = {a: ClaimVerification.model_validate(v) for a, v in (item.get("v3_alternatives") or {}).items()}
    return card, cvs, alts


def records(card, cvs) -> dict:
    claims = {c.id: c for c in r3.chain(card)}
    out = {}
    for cv in cvs:
        if cv.id not in claims:
            continue
        for side, lst in (("supports", cv.evidence), ("refutes", cv.counterevidence)):
            for r in lst:
                if r32.record_weight(r, claims[cv.id], side == "refutes", True) > 0:
                    out[(cv.id, r.record_id.replace("PMID:", ""))] = (side, r)
    return out


def main() -> dict:
    gold = {h["id"]: h for h in json.loads(SRC.read_text())["hypotheses"]}
    base = {u["id"]: u for u in units()}
    arms = {"old_v9": {h: {"card": None} for h in gold}}
    for name in ("A", "B"):
        f = CAL / f"sources_{name}.json"
        if f.exists():
            arms[name] = {h: r["items"][0] for h, r in json.loads(f.read_text()).items() if r["items"][0].get("card")}
    summary, rows = {}, []
    for name, data in arms.items():
        c = Counter()
        P, S, lab = [], [], []
        for h, g in gold.items():
            if name == "old_v9":
                u = base[h]
                card, cvs, alts = u["card"], u["cvs"], u["alts"]
            else:
                if h not in data or not data[h].get("verification"):
                    continue
                card, cvs, alts = arm_parts(data[h])
            recs = records(card, cvs)
            graph = {(x["link"], str(x["pmid"])): x for x in check_quotes(g.get("graph", []), g.get("cutoff") or base[h]["as_of"])
                     if x["_quote_ok"] and x["_before_cutoff"]}
            labels = {(x["link"], str(x["pmid"])): x for x in g.get("labels", [])}
            ref = {**graph, **{k: v for k, v in labels.items() if v.get("stance") != "neither"}}
            c["pairs"] += len(recs)
            c["pairs_in_reference"] += sum(1 for k in recs if k in ref)
            c["reference_pairs"] += len(ref)
            pre, out = nv.slots(card)
            out_recs = [r for (cid, _), (_, r) in recs.items() if cid in out]
            c["outcome_records"] += len(out_recs)
            c["outcome_with_number"] += sum(1 for r in out_recs if has_number(r))
            c["outcome_against"] += sum(1 for (cid, _), (s, _) in recs.items() if cid in out and s == "refutes")
            for k, (side, r) in recs.items():
                x = labels.get(k) or graph.get(k)
                if not x:
                    continue
                c["compared"] += 1
                im = r.qualifiers_match.get("intervention_match", "exact")
                im = "class" if im in ("class", "related_compound") else "exact"
                pairs = (("stance", side, x.get("stance")), ("design", r3.record_design(r), x.get("design")),
                         ("intervention", im, x.get("intervention_match")),
                         ("population", "adjacent" if r.qualifiers_match.get("population") == "no" else "exact", x.get("population_match")),
                         ("numeric_effect", has_number(r), (x.get("effect") or {}).get("value") is not None))
                for f, a, b in pairs:
                    c[f + "_agree"] += str(a) == str(b)
            e = r32.evaluate(card, cvs, alts, v34=True)
            P.append(e.P if e.gate == "pass" else -1.0)
            S.append(e.support_share)
            lab.append(base[h]["label"])
            rows.append({"arm": name, "id": h, "label": base[h]["label"], "P": e.P, "support_share": e.support_share,
                         "N": nv.novelty(card, cvs, e), "pairs": len(recs)})

        def auc(vals):
            pos, neg = [(v, 0) for v, l in zip(vals, lab) if l == 1], [(v, 0) for v, l in zip(vals, lab) if l == 0]
            return round(tied_auc(pos, neg), 3) if pos and neg else None
        n = max(1, c["compared"])
        summary[name] = {"units": len(lab), "pairs": c["pairs"], "share_of_reference_found": round(c["pairs_in_reference"] / max(1, c["reference_pairs"]), 3),
                         "outcome_records": c["outcome_records"], "outcome_with_number": c["outcome_with_number"],
                         "outcome_against": c["outcome_against"], "compared_with_argon": c["compared"],
                         "agreement": {f: round(c[f + "_agree"] / n, 3) for f in ("stance", "design", "intervention", "population", "numeric_effect")},
                         "auc_P": auc(P), "auc_support": auc(S)}
    (CAL / "sources_compare.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False) + "\n")
    return summary


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

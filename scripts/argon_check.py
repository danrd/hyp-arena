"""Re-check of Argon's pack 3 (specs/sources-experiment-2026-11-07.yaml, arm C and the gold labels), free:
quotes verbatim (abstract, or the PMC full text where PMC allows it), publication date before the cut-off, PMID exists;
then the labels against our records, the graph against our search, and the graph scored by the v3.4 rules.

    python -m scripts.argon_check     # reads longevity-kg reviews/argon-2026-11-07/task_cd.json -> calibration/argon_pack3_check.json
"""
from __future__ import annotations

import json
import re
from collections import Counter

from hyparena import backtest
from hyparena.backtest import tied_auc
from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification, EvidenceRecord
from hyparena.tools import pmc, pubmed
from scripts.ablation import units
from scripts.ceiling import CAL, KG

SRC = KG / "reviews" / "argon-2026-11-07" / "task_cd.json"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def check_quotes(items: list[dict], cutoff: str) -> list[dict]:
    pmids = sorted({str(x["pmid"]) for x in items})
    abs_ = pubmed.fetch(pmids)
    dates = backtest._pubdates(pmids)
    out = []
    for x in items:
        p = str(x["pmid"])
        a = abs_.get(p)
        text = ((a or {}).get("title", "") + " " + (a or {}).get("abstract", ""))
        in_abs = bool(x.get("quote")) and norm(x["quote"]) in norm(text)
        in_ft = False
        if not in_abs and x.get("quote") and x.get("source") == "full_text":
            ft = pmc.excerpt(p)
            in_ft = bool(ft) and norm(x["quote"]) in norm(ft)
        d = dates.get(p)
        out.append({**x, "_exists": a is not None, "_quote_ok": in_abs or in_ft, "_quote_where": "abstract" if in_abs else "full_text" if in_ft else None,
                    "_date": d, "_before_cutoff": d is not None and d <= cutoff})
    return out


def as_record(x: dict) -> EvidenceRecord:
    eff = x.get("effect") or {}
    phrase = eff.get("text") or ""
    kind, val = eff.get("kind"), eff.get("value")
    if val is not None and kind in ("smd", "d"):
        phrase = f"SMD = {abs(float(val))}"
    elif val is not None and kind == "ratio":
        phrase = f"RR {float(val)}"
    qm = {"intervention_match": {"exact": "exact", "class": "class"}.get(x.get("intervention_match"), "class")}
    if x.get("population_match") == "adjacent":
        qm["population"] = "no"
    cls = "none" if kind == "none" else "unclear"
    return EvidenceRecord(source="PubMed", record_id=f"PMID:{x['pmid']}", lab_or_cohort=f"PMID:{x['pmid']}",
                          design=x.get("design") if x.get("design") in ("rct", "non_randomised", "observational", "animal", "cells", "review", "meta_analysis") else "other",
                          n_total=x.get("n_total") if isinstance(x.get("n_total"), int) else None,
                          comparison=x.get("comparison") if x.get("comparison") in ("between_groups", "within_group", "none") else "unknown",
                          effect_reported=phrase, effect_class=cls, quote=x.get("quote", ""), quote_role="finding", qualifiers_match=qm)


def main() -> dict:
    data = json.loads(SRC.read_text())["hypotheses"]
    us = {u["id"]: u for u in units()}
    res, rows = {"quotes": Counter(), "labels": Counter(), "fields": Counter(), "recall": Counter()}, []
    for h in data:
        u = us.get(h["id"])
        if not u:
            continue
        g = check_quotes(h.get("graph", []), h.get("cutoff") or u["as_of"])
        lab = check_quotes(h.get("labels", []), h.get("cutoff") or u["as_of"])
        for x in g + lab:
            res["quotes"]["checked"] += 1
            res["quotes"]["pmid_exists"] += x["_exists"]
            res["quotes"]["quote_verbatim"] += x["_quote_ok"]
            res["quotes"]["before_cutoff"] += x["_before_cutoff"]
        # labels vs our records
        by = {c.id: c for c in u["cvs"]}
        claims = {c.id: c for c in r3.chain(u["card"])}
        ours = {}
        for cid, cv in by.items():
            for side, lst in (("supports", cv.evidence), ("refutes", cv.counterevidence)):
                for r in lst:
                    ours[(cid, r.record_id.replace("PMID:", ""))] = (side, r)
        for x in lab:
            o = ours.get((x["link"], str(x["pmid"])))
            if not o:
                continue
            side, r = o
            res["labels"]["compared"] += 1
            for f, ov, av in (("stance", side, x.get("stance")), ("design", r3.record_design(r), x.get("design")),
                              ("n_total", r.n_total, x.get("n_total")), ("comparison", r.comparison, x.get("comparison")),
                              ("intervention_match", r.qualifiers_match.get("intervention_match", "exact"), x.get("intervention_match")),
                              ("population_match", "adjacent" if r.qualifiers_match.get("population") == "no" else "exact", x.get("population_match")),
                              ("effect_number", d_any(r.effect_reported), (x.get("effect") or {}).get("value") is not None)):
                res["fields"][f + (":agree" if str(ov) == str(av) else ":differ")] += 1
        # recall: papers per link, ours vs graph (graph edges that passed the checks)
        good = [x for x in g if x["_quote_ok"] and x["_before_cutoff"]]
        ours_p = {(cid, p) for cid, p in ours}
        graph_p = {(x["link"], str(x["pmid"])) for x in good}
        res["recall"]["ours"] += len(ours_p)
        res["recall"]["graph_valid"] += len(graph_p)
        res["recall"]["both"] += len(ours_p & graph_p)
        res["recall"]["graph_rejected"] += len(g) - len(good)
        # arm C: the graph scored by the v3.4 rules on our card
        cvs = []
        for cid in claims:
            ev = [as_record(x) for x in good if x["link"] == cid and x.get("stance") == "supports"]
            ce = [as_record(x) for x in good if x["link"] == cid and x.get("stance") == "refutes"]
            cvs.append(ClaimVerification(id=cid, evidence=ev, counterevidence=ce))
        eC = r32.evaluate(u["card"], cvs, u["alts"], v34=True)
        eA = r32.evaluate(u["card"], u["cvs"], u["alts"], v34=True)
        pre, out = nv.slots(u["card"])
        num = lambda recs: sum(1 for x in recs if (x.get("effect") or {}).get("value") is not None)
        rows.append({"id": h["id"], "label": u["label"], "P_A": eA.P, "P_C": eC.P, "ss_A": eA.support_share, "ss_C": eC.support_share,
                     "N_A": nv.novelty(u["card"], u["cvs"], eA), "N_C": nv.novelty(u["card"], cvs, eC),
                     "against_out_A": sum(len(by[i].counterevidence) for i in out if i in by),
                     "against_out_C": sum(1 for x in good if x["link"] in out and x.get("stance") == "refutes"),
                     "numeric_effect_out_C": num([x for x in good if x["link"] in out])})

    def auc(k):
        pts = [(r[k], r["label"]) for r in rows]
        pos, neg = [(v, 0) for v, l in pts if l == 1], [(v, 0) for v, l in pts if l == 0]
        return round(tied_auc(pos, neg), 3) if pos and neg else None
    summary = {k: dict(v) for k, v in res.items()}
    summary["auc_15"] = {k: auc(k) for k in ("P_A", "P_C", "ss_A", "ss_C")}
    (CAL / "argon_pack3_check.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False) + "\n")
    return summary


def d_any(phrase: str) -> bool:
    from scripts.experiment_forecast import d_of
    return d_of(phrase) is not None


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

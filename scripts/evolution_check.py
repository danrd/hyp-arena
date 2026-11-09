"""Free: the evolution rules (manual section 11) and the hypothesis / experiment decomposition on saved evolution pairs.

    python -m scripts.evolution_check [--file evolution_60.json] [--pubmed]   # -> prospective/evolution_check_<file>.json
"""
from __future__ import annotations

import argparse
import json

from hyparena.card import evolution_rules as er
from hyparena.card import improvements as imp
from hyparena.card import novelty_v34 as nv
from hyparena.card import v3_extra
from hyparena.card.evolve_v3 import parent_parts
from scripts.v34_check import PROS


def logs_of(run: dict) -> dict:
    out = {}
    for c in run.get("calls", []):
        if c.get("kind") == "search":
            out[c.get("claim")] = c.get("pmids", [])
    return out


def axes_of(item: dict, extras: dict, as_of: str) -> tuple:
    card, cvs, alts = parent_parts(item)
    e = imp.evaluate(card, cvs, alts)
    ext = v3_extra.extras(card, cvs, item["v3"], as_of)
    ext = {**ext, **{k: v for k, v in extras.items() if v is not None}, "N": nv.novelty(card, cvs, e), "ai_role": card.ai_role}
    return imp.axes(e, item["v3"].get("headroom_I"), ext)


def main(fname: str, pubmed: bool) -> dict:
    ev = json.loads((PROS / fname).read_text())
    run = json.loads((PROS / "run_60.json").read_text())
    sf = json.loads((PROS / "scores_60_v34.json").read_text())
    out = {}
    for u, x in ev["pairs"].items():
        cr = x.get("child_run") or {}
        if not cr.get("items") or not cr["items"][0].get("card") or "v3" not in cr["items"][0]:
            out[u] = {"skipped": "no scored child"}
            continue
        pit, cit = run[u]["items"][0], cr["items"][0]
        as_of = run[u]["meta"].get("as_of") or ""
        pex = {k: sf.get(u, {}).get(k) for k in ("endpoint_clinical", "trend_pubmed", "feasibility")}
        cex = {**pex, "endpoint_clinical": x.get("child_endpoint")}
        pa, ca = axes_of(pit, pex, as_of), axes_of(cit, cex, as_of)
        dec = er.decompose(pa, ca)
        pc, pcv, palts = parent_parts(pit)
        cc, ccv, calts = parent_parts(cit)
        chk = er.check((pc, pcv, logs_of(run[u])), (cc, ccv, logs_of(cr)), mode=ev.get("mode", "tune"), as_of=as_of,
                       child_experiment_text=x.get("child_text", ""), parent_alts=palts, child_alts=calts,
                       scores={p: [None, None] for p in dec}, pubmed=pubmed)
        out[u] = {"decomposition": dec, "violations": chk["violations"], "warnings": chk["warnings"], "rules": chk["rules"]}
    summary = {"pairs": len(out), "with_violation": sum(1 for v in out.values() if v.get("violations")),
               "mean": {p: {k: round(sum(v["decomposition"][p][k] for v in out.values() if "decomposition" in v and p in v["decomposition"])
                                     / max(1, sum(1 for v in out.values() if "decomposition" in v and p in v["decomposition"])), 3)
                            for k in ("total", "hypothesis", "experiment")} for p in ("evidence", "funding", "frontier")}}
    res = {"summary": summary, "pairs": out}
    (PROS / f"evolution_check_{fname}").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="evolution_60.json")
    ap.add_argument("--pubmed", action="store_true")
    a = ap.parse_args()
    r = main(a.file, a.pubmed)
    print(json.dumps(r["summary"], indent=1))
    for u, v in r["pairs"].items():
        print(u, v.get("decomposition", v.get("skipped")), "violations", v.get("violations"), "warnings", v.get("warnings"))

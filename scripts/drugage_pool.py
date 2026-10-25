"""A free calibration pool from DrugAge: compounds with different depth of evidence at a date T, no labels, no model calls.

    python -m scripts.drugage_pool build --as-of 2015-12-31 --per-stratum 10 --out data/calibration/drugage_2015.json
    python -m scripts.drugage_pool run --pool data/calibration/drugage_2015.json --out runs/stage5/drugage_2015.json

`build` sorts the compounds of DrugAge into four strata by what was published by T (mouse papers: 2 or more (independent replication), 1; only
other species; nothing at all) and takes a fixed pseudo-random sample of each. `run` writes a card per compound by
code (a template, nothing is written by a model), verifies it against the curated DrugAge records only (PubMed
and the models are switched off) and ranks the pool with the usual rules, so every indicator that DrugAge can
decide varies across the pool. The pool shows how the profiles behave when the evidence differs; it says nothing
about whether the compounds work."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import defaultdict
from pathlib import Path

STRATA = ("deep", "shallow", "other_species", "none")
TEXT = "Dietary {c} extends the lifespan of {strain} mice."
SPAN = "{c} extends the lifespan of {strain} mice"
STRAINS = ("UM-HET3", "C57BL/6", "BALB/c", "CBA", "129/Sv", "DBA/2")   # the first one that DrugAge has no record of for the compound


def _stratum(mouse: int, other: int) -> str:
    return "deep" if mouse >= 2 else "shallow" if mouse >= 1 else "other_species" if other >= 1 else "none"


def build(as_of: str, per_stratum: int) -> dict:
    from hyparena.backtest import _pubdates, drugage_rows
    from hyparena.tools import compounds as cp
    rows = [r for r in drugage_rows() if r["pubmed_id"].strip() and r["compound_name"].strip()]
    dates = _pubdates(sorted({r["pubmed_id"].strip() for r in rows}))
    papers = defaultdict(lambda: {"mouse": set(), "other": set(), "first": None, "name": ""})
    for r in rows:
        p = r["pubmed_id"].strip()
        d = dates.get(p)
        if not d or any(ch in r["compound_name"] for ch in "+,;/"):
            continue
        k = cp.key(r["compound_name"])
        e = papers[k]
        e.setdefault("strains", set()).add(r["strain"].strip().lower()) if r["species"].strip() == "Mus musculus" else None
        e["name"] = e["name"] or r["compound_name"].strip()
        e["first"] = d if e["first"] is None else min(e["first"], d)
        if d <= as_of:
            e["mouse" if r["species"].strip() == "Mus musculus" else "other"].add(p)
    by = defaultdict(list)
    for k, e in papers.items():
        s = _stratum(len(e["mouse"]), len(e["other"]))
        if s == "none" and not (e["first"] and e["first"] > as_of):
            continue
        by[s].append((hashlib.sha1(k.encode()).hexdigest(), k, e))
    hyps = []
    for s in STRATA:
        taken = 0
        for _, k, e in sorted(by[s]):
            if taken >= per_stratum:
                break
            if cp.lookup(e["name"]) is None:                  # a name that is not one resolvable compound
                continue
            seen = e.get("strains", set())
            strain = next((x for x in STRAINS if not any(x.lower().split("/")[0] in t for t in seen)), STRAINS[-1])
            hyps.append({"id": f"cal{len(hyps) + 1:03d}", "compound": e["name"], "stratum": s, "strain": strain,
                         "text": TEXT.format(c=e["name"], strain=strain),
                         "mouse_papers_by_T": len(e["mouse"]), "other_papers_by_T": len(e["other"]), "first_date": e["first"]})
            taken += 1
    return {"source": {"name": "DrugAge", "as_of": as_of, "strata": list(STRATA), "per_stratum": per_stratum,
                       "note": "no labels; the pool shows how profiles behave under different depth of evidence"},
            "hypotheses": hyps}


def _card(h: dict, template: dict, n: int) -> dict:
    from hyparena.tools import compounds as cp
    c = copy.deepcopy(template)
    comp = cp.lookup(h["compound"])
    cid = f"CHEBI:{comp.chebi}" if comp and getattr(comp, "chebi", None) else None
    c["id"], c["raw_id"] = f"H-{n:04d}", h["id"]           # the pipeline numbers items H-0001.. in order
    c["claim_plain"] = f"Giving {h['compound']} to {h['strain']} mice extends their lifespan."
    c["pico"]["intervention"] = [{"type": "compound", "label": h["compound"], "id": cid, "regimen": "unknown", "route": "unknown"}]
    c["pico"]["comparator"] = {"type": "control", "label": "control diet"}
    k = next(x for x in c["claims"] if x["role"] == "outcome")
    c["claims"] = [k]
    k["relation"], k["object"] = "extends_lifespan_in", {"label": "Mus musculus", "id": None, "hallmark": None}
    k["id"] = "c1"
    c["pico"]["population"]["strain"] = h["strain"]
    k["subject"]["label"], k["subject"]["id"] = h["compound"], cid
    k["source_span"] = SPAN.format(c=h["compound"], strain=h["strain"])
    k["qualifiers"] = {"species": "Mus musculus", "strain": h["strain"]}
    c["edges"] = []
    for key in [k for k in c if "alternatives" in k]:     # a declared alternative would need a span of its own
        c[key] = []
    return c


def run(pool_path: str, out: str, template_path: str = "runs/stage5/g003.ab.json", K: int = 10000) -> dict:
    from hyparena.card import pipeline
    from hyparena.tools import pubmed
    pool = json.loads(Path(pool_path).read_text())
    template = json.loads(Path(template_path).read_text())["items"][0]["card"]
    hyps = pool["hypotheses"]
    pubmed.search = lambda q, retmax=8, as_of=None: []            # curated sources only: the PubMed search is off
    pubmed.fetch = lambda ids: {}
    res = pipeline.run([h["text"] for h in hyps], writer="calibration", fake=True, as_of=pool["source"]["as_of"], K=K,
                       cards=[_card(h, template, i) for i, h in enumerate(hyps, 1)], check_alternatives=False, dedup=False)
    res["meta"]["ids"] = [h["id"] for h in hyps]
    res["meta"]["pool"] = {"file": pool_path, "curated_only": True}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return res


STRATUM_RU = {"deep": "2+ работы на мышах", "shallow": "1 работа на мышах", "other_species": "только другие виды",
              "none": "до 2015 года ничего"}
TITLE_RU = "Калибровка профилей: 40 соединений DrugAge на конец 2015 года, разная глубина доказательств"


def bundle(run_path: str, pool_path: str, out: str) -> dict:
    """The site bundle of a pool run: titles name the stratum, the badge says it is a calibration pool (no models, no labels)."""
    from hyparena.site import bundle_from_result
    res = json.loads(Path(run_path).read_text())
    pool = {h["id"]: h for h in json.loads(Path(pool_path).read_text())["hypotheses"]}
    b = bundle_from_result(res, res["meta"]["ids"], None, TITLE_RU)
    for h in b["hypotheses"]:
        p = pool[h["id"]]
        h["title"] = f"{p['compound']} · {STRATUM_RU[p['stratum']]} · мыши {p['strain']}"
    b["meta"]["badge"] = "Калибровка"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(b, ensure_ascii=False, indent=1))
    return b


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--as-of", default="2015-12-31")
    b.add_argument("--per-stratum", type=int, default=10)
    b.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--pool", required=True)
    r.add_argument("--out", required=True)
    g = sub.add_parser("bundle", help="the site bundle of a run")
    g.add_argument("--run", required=True)
    g.add_argument("--pool", required=True)
    g.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "bundle":
        b = bundle(a.run, a.pool, a.out)
        print(a.out, len(b["hypotheses"]), "hypotheses")
    elif a.cmd == "build":
        pool = build(a.as_of, a.per_stratum)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(pool, ensure_ascii=False, indent=1))
        from collections import Counter
        print(a.out, dict(Counter(h["stratum"] for h in pool["hypotheses"])))
    else:
        res = run(a.pool, a.out)
        print(a.out, res["outcome_counts"], "calls", res["meta"]["calls"])


if __name__ == "__main__":
    main()

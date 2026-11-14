"""Free experiment, part 3: how to share the reading budget of a hypothesis over its searches (plan
docs/plans/search-2026-11-14.md; rule in specs/benchmark-search-2026-11-12.yaml, free_experiments_2026_11_14).

    python -m scripts.search_budget_check     # longevity-kg/reviews/argon-2026-11-12/search_budget_check.json, search_orders.json

A saved run searches every claim of the card (c1, ...), every analog claim (an1, ...) and every proposed alternative
(p1, ...) and reads 20 papers of each. Here every search has its candidates ordered as the best free variant so far (top 200
of each query, references and citing papers of the first 5, BM25), saved to search_orders.json (the first 150 per search) for
the later relevance-filter experiment. The same total number of reading slots (20 x the number of searches) is then shared by
weights per kind of search; recall of the gold in the union.
"""
from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path

from hyparena.tools import pubmed
from scripts.bench_search import gold_answer, valid
from scripts.search_expand_check import LCACHE, links
from scripts.search_misses import _esearch
from scripts.search_rerank_check import _terms, _tok, bm25

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-12"
CAL = KG / "hypothesis_sources" / "calibration"
ORDERS = DIR / "search_orders.json"
PLANS = {"equal_20": {"card": 1, "analog": 1, "alternative": 1},
         "card_x2": {"card": 2, "analog": 1, "alternative": 1},
         "card_x4_alt_half": {"card": 4, "analog": 1, "alternative": 0.5},
         "card_x4_analog_x2_alt_half": {"card": 4, "analog": 2, "alternative": 0.5},
         "card_x8_alt_quarter": {"card": 8, "analog": 2, "alternative": 0.25},
         "no_alternatives": {"card": 1, "analog": 1, "alternative": 0},
         "card_only": {"card": 1, "analog": 0, "alternative": 0}}


def kind(claim_id: str) -> str:
    return "alternative" if claim_id.startswith("p") else "analog" if claim_id.startswith("an") else "card"


def orders() -> dict:
    if ORDERS.exists():
        return json.loads(ORDERS.read_text())
    key = json.loads((DIR / "pack_18_key.json").read_text())
    runs = {}
    for f in sorted(glob.glob(str(CAL / "run_*_v10.json"))):
        runs.update(json.loads(Path(f).read_text()))
    cache = json.loads((DIR / "mesh_search_cache.json").read_text())
    lc = json.loads(LCACHE.read_text()) if LCACHE.exists() else {}
    out = {}
    for sid, k in sorted(key.items()):
        T = k["T"] if len(k["T"]) > 7 else k["T"] + "-28"
        out[sid] = {}
        for c in runs[k["unit"]]["calls"]:
            if c.get("kind") != "search_plan":
                continue
            qs = c.get("guarded") or c.get("model_queries") or []
            terms = _terms(qs)
            cand = list(dict.fromkeys(p for q in qs for p in _esearch(q, T, cache)["ids"][:200]))
            recs = pubmed.fetch(cand)
            doc = lambda p, r: _tok(f"{(r.get(p) or {}).get('title', '')} {(r.get(p) or {}).get('abstract', '')}")
            base = bm25(terms, {p: doc(p, recs) for p in cand})
            new = [x for s in base[:5] for n in ("pubmed_pubmed_refs", "pubmed_pubmed_citedin") for x in links(s, n, lc)]
            new = [p for p in dict.fromkeys(new) if p not in cand][:600]
            r2 = pubmed.fetch(new)
            new = [p for p in new if (r2.get(p) or {}).get("year") and str(r2[p]["year"]) <= T[:4]]
            allrec = {**recs, **r2}
            out[sid][c["claim"]] = {"queries": qs, "order": bm25(terms, {p: doc(p, allrec) for p in cand + new})[:150]}
        print(sid, len(out[sid]), flush=True)
    ORDERS.write_text(json.dumps(out) + "\n")
    return out


def run() -> dict:
    ans = gold_answer()
    key = json.loads((DIR / "pack_18_key.json").read_text())
    pm = json.loads((DIR / "pack_18_pubmed.json").read_text())
    od = orders()
    gold, hold = {}, {}
    for sid, g in ans.items():
        k = key[sid]; T = k["T"] if len(k["T"]) > 7 else k["T"] + "-28"
        gold[sid] = {p["pmid"] for p in g["papers"] if valid(pm, p["pmid"]) and (pm[p["pmid"]].get("earliest") or "") <= T}
        hold[sid] = bool(k["holdout"])
    out = {}
    for name, w in PLANS.items():
        sel = defaultdict(set)
        for sid, claims in od.items():
            slots = 20 * len(claims)
            tot = sum(w[kind(c)] for c in claims) or 1
            for c, v in claims.items():
                sel[sid] |= set(v["order"][: round(slots * w[kind(c)] / tot)])
        rec = lambda ids: round(sum(len(sel[s] & gold[s]) for s in ids) / sum(len(gold[s]) for s in ids), 3)
        out[name] = {"recall": rec(list(gold)), "recall_holdout": rec([s for s in gold if hold[s]]),
                     "trials_with_a_gold_paper": sum(bool(sel[s] & gold[s]) for s in gold),
                     "papers_per_trial_median": sorted(len(sel[s]) for s in gold)[len(gold) // 2]}
    kinds = defaultdict(int)
    for claims in od.values():
        for c in claims:
            kinds[kind(c)] += 1
    out["searches_by_kind"] = dict(kinds)
    (DIR / "search_budget_check.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

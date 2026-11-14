"""Free experiments, part 2: candidates from links between papers, ordered by word match (plan docs/plans/search-2026-11-14.md,
options Г1 and Г2; rule in specs/benchmark-search-2026-11-12.yaml, free_experiments_2026_11_14). PubMed only, no model call.

    python -m scripts.search_expand_check     # longevity-kg/reviews/argon-2026-11-12/search_expand_check.json

Per claim: candidates = the top 200 of each model-written query, ordered by BM25 (scripts/search_rerank_check.py). Then the
first 5 papers are seeds and their linked papers (dated on or before T) join the candidates, and BM25 orders all again:
  cite     the seeds' references and the papers citing them (NCBI elink), as the pipeline's citation step;
  similar  PubMed's similar articles of the seeds (the first 40 each);
  reviews  the references of the reviews among the first 20 (publication type Review, Systematic Review, Meta-Analysis);
  all      the three together.
20 papers per claim; recall of the gold in the union over the claims of a trial.
"""
from __future__ import annotations

import glob
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from hyparena.tools import pubmed
from scripts.bench_search import gold_answer, valid
from scripts.search_misses import _esearch
from scripts.search_rerank_check import KEEP, _terms, _tok, bm25

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-12"
CAL = KG / "hypothesis_sources" / "calibration"
LCACHE = DIR / "search_links_cache.json"
EL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
_last = [0.0]
REVIEW = {"Review", "Systematic Review", "Meta-Analysis"}


def links(pmid: str, name: str, cache: dict) -> list[str]:
    k = f"{name}|{pmid}"
    if k in cache:
        return cache[k]
    for attempt in range(4):
        wait = 0.36 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            q = urllib.parse.urlencode({"dbfrom": "pubmed", "db": "pubmed", "id": pmid, "linkname": name, "retmode": "json"})
            r = json.loads(urllib.request.urlopen(EL + "?" + q, timeout=60).read())
            cache[k] = [str(x) for ls in r.get("linksets", []) for db in ls.get("linksetdbs", []) for x in db.get("links", [])]
            return cache[k]
        except Exception:
            time.sleep(2 ** attempt)
    return []


def run() -> dict:
    ans = gold_answer()
    key = json.loads((DIR / "pack_18_key.json").read_text())
    pm = json.loads((DIR / "pack_18_pubmed.json").read_text())
    runs = {}
    for f in sorted(glob.glob(str(CAL / "run_*_v10.json"))):
        runs.update(json.loads(Path(f).read_text()))
    cache = json.loads((DIR / "mesh_search_cache.json").read_text())
    lc = json.loads(LCACHE.read_text()) if LCACHE.exists() else {}
    sel = defaultdict(lambda: defaultdict(set)); gold, hold = {}, {}
    try:
        for sid, g in sorted(ans.items()):
            k = key[sid]; T = k["T"] if len(k["T"]) > 7 else k["T"] + "-28"
            gold[sid] = {p["pmid"] for p in g["papers"] if valid(pm, p["pmid"]) and (pm[p["pmid"]].get("earliest") or "") <= T}
            hold[sid] = bool(k["holdout"])
            for c in runs[k["unit"]]["calls"]:
                if c.get("kind") != "search_plan":
                    continue
                qs = c.get("guarded") or c.get("model_queries") or []
                terms = _terms(qs)
                cand = list(dict.fromkeys(p for q in qs for p in _esearch(q, T, cache)["ids"][:200]))
                recs = pubmed.fetch(cand)
                doc = lambda p, recs: _tok(f"{(recs.get(p) or {}).get('title', '')} {(recs.get(p) or {}).get('abstract', '')}")
                base = bm25(terms, {p: doc(p, recs) for p in cand})
                sel["bm25"][sid] |= set(base[:KEEP])
                seeds = base[:5]
                extra = {"cite": [x for s in seeds for n in ("pubmed_pubmed_refs", "pubmed_pubmed_citedin") for x in links(s, n, lc)],
                         "similar": [x for s in seeds for x in links(s, "pubmed_pubmed", lc)[:40]],
                         "reviews": [x for s in base[:KEEP] if REVIEW & set((recs.get(s) or {}).get("pubtypes") or [])
                                     for x in links(s, "pubmed_pubmed_refs", lc)]}
                extra["all"] = extra["cite"] + extra["similar"] + extra["reviews"]
                for name, ids in extra.items():
                    new = [p for p in dict.fromkeys(ids) if p not in cand][:600]
                    r2 = pubmed.fetch(new)
                    new = [p for p in new if (r2.get(p) or {}).get("year") and str(r2[p]["year"]) <= T[:4]]   # year guard (coarse)
                    allrec = {**recs, **r2}
                    order = bm25(terms, {p: doc(p, allrec) for p in cand + new})
                    sel[name][sid] |= set(order[:KEEP])
                    sel[f"{name}_pool"][sid] |= set(cand + new)
            print(sid, len(gold[sid]), {v: len(sel[v][sid] & gold[sid]) for v in ("bm25", "cite", "similar", "reviews", "all", "all_pool")}, flush=True)
            LCACHE.write_text(json.dumps(lc) + "\n")
    finally:
        LCACHE.write_text(json.dumps(lc) + "\n")
    out = {}
    for v in sel:
        def rec(ids):
            n = sum(len(gold[s]) for s in ids)
            return round(sum(len(sel[v][s] & gold[s]) for s in ids) / n, 3) if n else None
        out[v] = {"recall": rec(list(gold)), "recall_holdout": rec([s for s in gold if hold[s]]),
                  "trials_with_a_gold_paper": sum(bool(sel[v][s] & gold[s]) for s in gold),
                  "papers_per_trial_median": sorted(len(sel[v][s]) for s in gold)[len(gold) // 2]}
    out["note"] = "linked papers are dated by publication year only (a paper of the year of T after T may pass); the gold is dated exactly"
    (DIR / "search_expand_check.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

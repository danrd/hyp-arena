"""Free experiments on choosing the 20 papers per claim (plan docs/plans/search-2026-11-14.md, step 2; the admission rule is in
specs/benchmark-search-2026-11-12.yaml, free_experiments_2026_11_14). PubMed only, no model call.

    python -m scripts.search_rerank_check     # longevity-kg/reviews/argon-2026-11-12/search_rerank_check.json

Per claim of a saved run: its model-written queries, each with its PubMed ids before T (cache of scripts/mesh_search_check.py).
Candidates: the top N of each query. Orders compared at 20 papers per claim:
  round_robin  the pipeline's merge (the first hit of each query, then the second, ...);
  votes        reciprocal rank fusion over the queries (a paper several queries return goes up);
  bm25         the query terms (field tags and operators removed) against title and abstract, within the claim's candidates;
  votes+bm25   the two orders fused;
  relax        round_robin after a query with under 20 hits is repeated without its last AND block.
Recall: the gold papers (valid, on or before T) in the union over the claims of a trial.
"""
from __future__ import annotations

import glob
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from hyparena.tools import pubmed
from scripts.bench_search import valid
from scripts.search_misses import _blocks, _esearch

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-12"
CAL = KG / "hypothesis_sources" / "calibration"
KEEP = 20
STOP = set("and or not the of in on for with to a an by from tiab mesh mh pt majr title abstract terms all fields nm sh la "
           "review humans human english".split())


def _terms(queries: list[str]) -> list[str]:
    words = []
    for q in queries:
        q = re.sub(r"\[[^\]]*\]", " ", q)
        words += [w for w in re.findall(r"[a-z][a-z0-9-]{2,}", q.lower()) if w not in STOP]
    return list(dict.fromkeys(words))


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9-]{2,}", (s or "").lower())


def bm25(terms: list[str], docs: dict[str, list[str]]) -> list[str]:
    n = len(docs) or 1
    avg = sum(len(d) for d in docs.values()) / n or 1
    df = Counter(t for d in docs.values() for t in set(d))
    score = {}
    for p, d in docs.items():
        tf = Counter(d)
        score[p] = sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avg))
                       for t in terms if t in tf)
    return sorted(docs, key=lambda p: -score[p])


def rrf(orders: list[list[str]], k: int = 60) -> list[str]:
    s = defaultdict(float)
    for o in orders:
        for i, p in enumerate(o):
            s[p] += 1 / (k + i + 1)
    return sorted(s, key=lambda p: -s[p])


def round_robin(lists: list[list[str]], keep: int) -> list[str]:
    out = []
    for i in range(max((len(x) for x in lists), default=0)):
        for lst in lists:
            if i < len(lst) and lst[i] not in out:
                out.append(lst[i])
        if len(out) >= keep:
            break
    return out[:keep]


def run() -> dict:
    ans = {i["id"]: i for i in json.loads((DIR / "pack_18_answer.json").read_text())["items"]}
    key = json.loads((DIR / "pack_18_key.json").read_text())
    pm = json.loads((DIR / "pack_18_pubmed.json").read_text())
    runs = {}
    for f in sorted(glob.glob(str(CAL / "run_*_v10.json"))):
        runs.update(json.loads(Path(f).read_text()))
    cf = DIR / "mesh_search_cache.json"
    cache = json.loads(cf.read_text())
    sel = defaultdict(lambda: defaultdict(set)); gold, hold, pool = {}, {}, defaultdict(set)
    try:
        for sid, g in sorted(ans.items()):
            k = key[sid]; T = k["T"] if len(k["T"]) > 7 else k["T"] + "-28"
            gold[sid] = {p["pmid"] for p in g["papers"] if valid(pm, p["pmid"]) and (pm[p["pmid"]].get("earliest") or "") <= T}
            hold[sid] = bool(k["holdout"])
            r = runs[k["unit"]]
            for c in r["calls"]:
                if c.get("kind") == "search":
                    sel["saved_run"][sid] |= set(c.get("pmids") or [])
                if c.get("kind") != "search_plan":
                    continue
                qs = c.get("guarded") or c.get("model_queries") or []
                lists = [_esearch(q, T, cache)["ids"] for q in qs]
                sel["round_robin"][sid] |= set(round_robin(lists, KEEP))
                relaxed = []
                for q, ids in zip(qs, lists):
                    bl = _blocks(q)
                    while len(ids) < 20 and len(bl) > 2:
                        bl = bl[:-1]
                        ids = _esearch(" AND ".join(bl), T, cache)["ids"]
                    relaxed.append(ids)
                sel["relax"][sid] |= set(round_robin(relaxed, KEEP))
                terms = _terms(qs)
                for n in (100, 200):
                    tops = [x[:n] for x in lists]
                    cand = list(dict.fromkeys(p for x in tops for p in x))
                    pool[n] |= {(sid, p) for p in cand}
                    recs = pubmed.fetch(cand)
                    docs = {p: _tok(f"{(recs.get(p) or {}).get('title', '')} {(recs.get(p) or {}).get('abstract', '')}") for p in cand}
                    v, b = rrf(tops), bm25(terms, docs)
                    sel[f"votes@{n}"][sid] |= set(v[:KEEP])
                    sel[f"bm25@{n}"][sid] |= set(b[:KEEP])
                    sel[f"votes+bm25@{n}"][sid] |= set(rrf([v, b])[:KEEP])
                    sel[f"pool@{n}"][sid] |= set(cand)
                    rl = [x[:n] for x in relaxed]
                    cr = list(dict.fromkeys(p for x in rl for p in x))
                    recs = pubmed.fetch(cr)
                    dr = {p: _tok(f"{(recs.get(p) or {}).get('title', '')} {(recs.get(p) or {}).get('abstract', '')}") for p in cr}
                    sel[f"relax+votes+bm25@{n}"][sid] |= set(rrf([rrf(rl), bm25(terms, dr)])[:KEEP])
            print(sid, len(gold[sid]), {v: len(sel[v][sid] & gold[sid]) for v in ("saved_run", "round_robin", "votes@200", "bm25@200", "votes+bm25@200", "pool@200")}, flush=True)
    finally:
        cf.write_text(json.dumps(cache) + "\n")
    out = {}
    for v in sel:
        def rec(ids):
            n = sum(len(gold[s]) for s in ids)
            return round(sum(len(sel[v][s] & gold[s]) for s in ids) / n, 3) if n else None
        out[v] = {"recall": rec(list(gold)), "recall_holdout": rec([s for s in gold if hold[s]]),
                  "trials_with_a_gold_paper": sum(bool(sel[v][s] & gold[s]) for s in gold),
                  "papers_per_trial_median": sorted(len(sel[v][s]) for s in gold)[len(gold) // 2]}
    out["gold_papers"] = sum(len(x) for x in gold.values())
    (DIR / "search_rerank_check.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

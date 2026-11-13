"""Where are the gold papers of the search benchmark lost? (Argon pack 18, saved searches v10.) Free: PubMed E-utilities only.

    python -m scripts.search_misses        # longevity-kg/reviews/argon-2026-11-12/search_misses.json

The search of one claim (hyparena/card/search.py `retrieve`, mode "model"): up to 4 LLM-written queries, each cut to the top
20 by relevance with the date guard (pdat <= T); the lists are interleaved, citation neighbours of the first seeds are added,
keyword queries fill the rest; the first 20 go to the reader. Each gold paper of pack 18 (valid, on or before T) is put at
the first step where it is lost:

  read            a record of a claim (evidence or counterevidence)
  given_not_read  in the abstracts the reader got, no record
  ranked_out      a saved query of the trial matches it (PubMed, same date guard) but it is not among the 20 given
  date_guard      public on or before T but its publication date (pdat) is after T: no query with the guard can return it
  no_query        none of the trial's saved queries matches it; for the queries of its link, the AND-blocks it fails
                  (population, intervention, outcome, design filter, other) are recorded
Plus: whether the card has a claim of the paper's kind at all (step papers need a step claim).
"""
from __future__ import annotations

import glob
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-12"
CAL = KG / "hypothesis_sources" / "calibration"
ES = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
CACHE = DIR / "search_misses_cache.json"
STEP = {"delivery", "engagement", "pathway", "effect"}
_last = [0.0]


def _esearch(term: str, as_of: str | None, cache: dict) -> dict:
    k = f"{as_of}|{term}"
    if k in cache:
        return cache[k]
    p = {"db": "pubmed", "term": term, "retmax": 500, "retmode": "json"}
    if as_of:
        p.update({"datetype": "pdat", "mindate": "1800/01/01", "maxdate": as_of.replace("-", "/")})
    for attempt in range(5):
        wait = 0.36 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = json.loads(urllib.request.urlopen(ES + "?" + urllib.parse.urlencode(p), timeout=60).read())["esearchresult"]
            if "ERROR" in r:
                raise RuntimeError(r["ERROR"])
            cache[k] = {"count": int(r.get("count", 0)), "ids": r.get("idlist", [])}
            if len(cache) % 50 == 0:                      # keep progress if the run is stopped
                CACHE.write_text(json.dumps(cache) + "\n")
            return cache[k]
        except Exception:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"esearch failed: {term[:100]}")


def _blocks(q: str) -> list[str]:
    """Top-level AND blocks of a query (parentheses respected)."""
    out, depth, cur, i = [], 0, "", 0
    while i < len(q):
        c = q[i]
        depth += c == "("
        depth -= c == ")"
        if depth == 0 and q[i:i + 5].upper() == " AND ":
            out.append(cur.strip())
            cur, i = "", i + 5
            continue
        cur += c
        i += 1
    out.append(cur.strip())
    return [b for b in out if b]


def _kind(b: str, card: dict) -> str:
    low = b.lower()
    if "[pt]" in low or "random" in low or "trial" in low:
        return "design_filter"
    pop = json.dumps(card.get("pico", {}).get("population", {})).lower()
    inter = " ".join(i.get("label", "") for i in card.get("pico", {}).get("intervention", [])).lower()
    words = set(re.findall(r"[a-z][a-z\-]{3,}", low))
    if words & set(re.findall(r"[a-z][a-z\-]{3,}", inter)):
        return "intervention"
    if words & {"aged", "elderly", "older", "frail", "frailty", "sarcopenia", "sarcopenic", "postmenopausal", "women", "adults",
                "nursing", "residents", "community-dwelling", "pre-frail", "prefrail", "patients"} or \
       words & set(re.findall(r"[a-z][a-z\-]{4,}", pop)):
        return "population"
    return "outcome_or_other"


def run() -> dict:
    ans = {i["id"]: i for i in json.loads((DIR / "pack_18_answer.json").read_text())["items"]}
    key = json.loads((DIR / "pack_18_key.json").read_text())
    pm = json.loads((DIR / "pack_18_pubmed.json").read_text())
    runs = {}
    for f in sorted(glob.glob(str(CAL / "run_*_v10.json"))):
        runs.update(json.loads(Path(f).read_text()))
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    rows, qstats = [], []
    try:
        for sid, g in sorted(ans.items()):
            k = key[sid]
            T = k["T"] if len(k["T"]) > 7 else k["T"] + "-28"
            r = runs[k["unit"]]
            it = r["items"][0]
            card = it.get("card") or {}
            links = {c["id"]: c.get("link") for c in card.get("claims") or []}
            given = defaultdict(set)
            plans = {}
            for c in r["calls"]:
                if c.get("kind") == "search" and c.get("claim"):
                    given[c["claim"]] |= set(c.get("pmids") or [])
                if c.get("kind") == "search_plan":
                    plans[c["claim"]] = c.get("guarded") or c.get("model_queries") or []
            given_all = set().union(*given.values()) if given else set()
            read = {e["record_id"].split(":", 1)[-1] for cv in ((it.get("verification") or {}).get("claims") or [])
                    for e in (cv.get("evidence") or []) + (cv.get("counterevidence") or [])}
            gold = [p for p in g["papers"] if pm.get(p["pmid"], {}).get("exists") and
                    (pm[p["pmid"]].get("earliest") or "") <= T]
            ids = " OR ".join(f"{p['pmid']}[uid]" for p in gold)
            in_pdat = set(_esearch(f"({ids})", T, cache)["ids"]) if gold else set()
            match = defaultdict(set)                       # pmid -> claims whose saved query matches it
            for cl, qs in plans.items():
                for q in qs:
                    res = _esearch(f"({q}) AND ({ids})", T, cache) if gold else {"ids": []}
                    for x in res["ids"]:
                        match[x].add(cl)
                    qstats.append({"sid": sid, "claim": cl, "link": links.get(cl), "hits": _esearch(q, T, cache)["count"],
                                   "blocks": len(_blocks(q))})
            for p in gold:
                want = STEP if p["category"] == "step" or (p["category"] == "against" and p.get("step")) else {"outcome"}
                own = [cl for cl in plans if links.get(cl) in want]
                if p["pmid"] in read:
                    stage = "read"
                elif p["pmid"] in given_all:
                    stage = "given_not_read"
                elif p["pmid"] not in in_pdat:
                    stage = "date_guard"
                elif match.get(p["pmid"]):
                    stage = "ranked_out"
                else:
                    stage = "no_query"
                fails = []
                if stage == "no_query":
                    for cl in own:
                        for q in plans[cl]:
                            bad = [_kind(b, card) for b in _blocks(q)
                                   if p["pmid"] not in _esearch(f"({b}) AND ({ids})", T, cache)["ids"]]
                            fails.append(bad)
                rows.append({"sid": sid, "pmid": p["pmid"], "cat": p["category"], "pop": p.get("population"), "stage": stage,
                             "card_has_claim_kind": bool(own), "matched_by": sorted(match.get(p["pmid"], [])),
                             "matched_own_link": bool(set(match.get(p["pmid"], [])) & set(own)), "failed_blocks": fails})
    finally:
        CACHE.write_text(json.dumps(cache) + "\n")
    single_fail = Counter(f[0] for r in rows for f in r["failed_blocks"] if len(f) == 1)
    any_fail = Counter(b for r in rows for f in r["failed_blocks"] for b in set(f))
    best = Counter(min((len(f) for f in r["failed_blocks"]), default=None) for r in rows if r["stage"] == "no_query")
    hits = sorted(q["hits"] for q in qstats)
    summ = {
        "papers": len(rows),
        "stage": dict(Counter(r["stage"] for r in rows)),
        "stage_by_category": {c: dict(Counter(r["stage"] for r in rows if r["cat"] == c)) for c in sorted({r["cat"] for r in rows})},
        "no_claim_of_its_kind": dict(Counter(r["stage"] for r in rows if not r["card_has_claim_kind"])),
        "no_query_fewest_failed_blocks_on_own_link": {str(k): v for k, v in best.items()},
        "no_query_single_failed_block": dict(single_fail),
        "no_query_block_kinds_failed": dict(any_fail),
        "queries": {"n": len(qstats), "hits_median": hits[len(hits) // 2] if hits else None,
                    "hits_0": sum(h == 0 for h in hits), "hits_under_20": sum(h < 20 for h in hits),
                    "blocks_median": sorted(q["blocks"] for q in qstats)[len(qstats) // 2] if qstats else None,
                    "outcome_link_hits_median": (lambda h: h[len(h) // 2] if h else None)(sorted(q["hits"] for q in qstats if q["link"] == "outcome"))},
    }
    (DIR / "search_misses.json").write_text(json.dumps({"summary": summ, "papers": rows, "queries": qstats}, indent=1) + "\n")
    return summ


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

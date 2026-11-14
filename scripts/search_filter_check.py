"""Paid experiment: a cheap LLM as the relevance filter before reading (plan docs/plans/search-2026-11-14.md, option Б4; rule
in specs/benchmark-search-2026-11-12.yaml, filter_experiment_2026_11_14).

    python -m scripts.search_filter_check dry                 # free: calls, tokens, price
    ALLOW_PAID=1 MAX_USD=1.5 python -m scripts.search_filter_check run
    python -m scripts.search_filter_check score               # free

Per search of a saved run (a card claim, an analog claim or a proposed alternative): the first 100 candidates of the best
free order (scripts/search_budget_check.py: top 200 of each query, citations of the first 5, BM25) are rated 0-3 by the cheap
model from title and abstract (prompt search_relevance/v1, 20 records per call). The 20 read are then the highest rated,
BM25 order within a rating. Recall of the gold against BM25 alone at the same 20 per search.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from hyparena.tools import pubmed
from scripts.bench_search import gold_answer, valid
from scripts.search_budget_check import orders

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-12"
CAL = KG / "hypothesis_sources" / "calibration"
OUT = DIR / "search_filter_scores.json"
CONFIG, FAMILY, TOP, BATCH, ABS = "configs/v3-flash-n10.yaml", "deepseek", 100, 20, 900
PRICE = (0.15, 0.6)          # USD per M tokens, deepseek flash, no peak price (weekend)


def _runs() -> dict:
    runs = {}
    for f in sorted(glob.glob(str(CAL / "run_*_v10.json"))):
        runs.update(json.loads(Path(f).read_text()))
    return runs


def _target(item: dict, cid: str) -> str:
    card = item.get("card") or {}
    for c in card.get("claims") or []:
        if c["id"] == cid:
            m = (c.get("qualifiers") or {}).get("measure")
            return f"claim of the hypothesis: {c['subject']['label']} — {c['relation']} — {c['object']['label']}" + (f" (measure: {m})" if m else "")
    for c in (item.get("verification") or {}).get("claims") or []:
        if c["id"] == cid and c.get("claim"):
            x = c["claim"]
            return f"the same effect in another species or for a related intervention: {x['subject']['label']} — {x['relation']} — {x['object']['label']}"
    return "a competing explanation of the hypothesis's result (see the queries)" if cid.startswith("p") else "see the queries"


def jobs() -> list[dict]:
    key = json.loads((DIR / "pack_18_key.json").read_text())
    runs, od, out = _runs(), orders(), []
    for sid, claims in sorted(od.items()):
        item = runs[key[sid]["unit"]]["items"][0]
        card = item.get("card") or {}; p = card.get("pico") or {}
        for cid, v in claims.items():
            ids = v["order"][:TOP]
            for b in range(0, len(ids), BATCH):
                out.append({"sid": sid, "claim": cid, "ids": ids[b:b + BATCH],
                            "vars": {"claim_plain": card.get("claim_plain", ""),
                                     "intervention": "; ".join(i.get("label", "") for i in p.get("intervention") or []),
                                     "population": (p.get("population") or {}).get("label", ""),
                                     "target": _target(item, cid), "queries": " | ".join(v["queries"])[:1500]}})
    return out


def _records(ids: list[str]) -> list[dict]:
    rec = pubmed.fetch(ids)
    return [{"n": i + 1, "title": (rec.get(p) or {}).get("title", ""), "year": (rec.get(p) or {}).get("year", ""),
             "types": ", ".join(((rec.get(p) or {}).get("pubtypes") or [])[:3]),
             "abstract": ((rec.get(p) or {}).get("abstract") or "")[:ABS]} for i, p in enumerate(ids)]


def dry() -> dict:
    from hyparena.card.llm import render
    js = jobs()
    chars = sum(len(render("search_relevance", "v1", **j["vars"], records=_records(j["ids"]), history_text="")) for j in js[::10]) * 10
    tin, tout = chars / 3.8, len(js) * 130
    return {"searches": len({(j["sid"], j["claim"]) for j in js}), "records": sum(len(j["ids"]) for j in js), "calls": len(js),
            "tokens_in_est": round(tin), "tokens_out_est": round(tout),
            "usd_est": round(tin * PRICE[0] / 1e6 + tout * PRICE[1] / 1e6, 2), "model": "deepseek flash, no peak price"}


def run() -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask
    from hyparena.card.pipeline import _client
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    js = [j for j in jobs() if not all(f"{j['sid']}|{j['claim']}|{p}" in done for p in j["ids"])]
    client, _ = _client(CONFIG, False, len(js) * 2 + 10)
    lock, tok = threading.Lock(), Counter()

    def one(j):
        log: list = []
        n = len(j["ids"])
        ok = lambda v: [] if isinstance(v.get("scores"), dict) and len(v["scores"]) >= n - 1 else [f'"scores" must rate all {n} records']
        try:
            value, _ = ask(client, role="search_relevance", family=FAMILY, template="search_relevance", version="v1",
                           variables={**j["vars"], "records": _records(j["ids"])}, validate=ok, rounds=2, log=log)
        except Exception as e:                                  # the USD cap or a provider error: keep what is done
            value = None; log.append({"error": str(e)[:200]})
        with lock:
            for x in log:
                tok["in"] += int(x.get("tokens_in") or 0); tok["out"] += int(x.get("tokens_out") or 0); tok["calls"] += 1
            for i, p in enumerate(j["ids"]):
                s = ((value or {}).get("scores") or {}).get(str(i + 1))
                if isinstance(s, (int, float)):
                    done[f"{j['sid']}|{j['claim']}|{p}"] = s
            if tok["calls"] % 40 == 0:
                OUT.write_text(json.dumps(done) + "\n")

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, js))
    OUT.write_text(json.dumps(done) + "\n")
    usd = tok["in"] * PRICE[0] / 1e6 + tok["out"] * PRICE[1] / 1e6
    return {"jobs": len(js), "rated": len(done), "tokens": dict(tok), "usd": round(usd, 3)}


def score() -> dict:
    ans = gold_answer(); key = json.loads((DIR / "pack_18_key.json").read_text())
    pm = json.loads((DIR / "pack_18_pubmed.json").read_text())
    od, sc = orders(), json.loads(OUT.read_text())
    gold, hold = {}, {}
    for sid, g in ans.items():
        k = key[sid]; T = k["T"] if len(k["T"]) > 7 else k["T"] + "-28"
        gold[sid] = {p["pmid"] for p in g["papers"] if valid(pm, p["pmid"]) and (pm[p["pmid"]].get("earliest") or "") <= T}
        hold[sid] = bool(k["holdout"])
    sel = defaultdict(lambda: defaultdict(set)); dist = Counter(); gold_scores = Counter(); missing = 0
    for sid, claims in od.items():
        for cid, v in claims.items():
            for depth in (40, 60, 100):
                ids = v["order"][:depth]
                rated = sorted(range(len(ids)), key=lambda i: (-(sc.get(f"{sid}|{cid}|{ids[i]}", -1)), i))
                for keep in (10, 20):
                    sel[f"llm_top{depth}_keep{keep}"][sid] |= {ids[i] for i in rated[:keep]}
            for keep in (10, 20):
                sel[f"bm25_keep{keep}"][sid] |= set(v["order"][:keep])
            sel["candidates_100"][sid] |= set(v["order"][:100])
            for p in v["order"][:100]:
                s = sc.get(f"{sid}|{cid}|{p}")
                missing += s is None
                dist[s] += 1
                if p in gold[sid]:
                    gold_scores[s] += 1
    out = {}
    for name in sorted(sel):
        rec = lambda ids: round(sum(len(sel[name][s] & gold[s]) for s in ids) / sum(len(gold[s]) for s in ids), 3)
        out[name] = {"recall": rec(list(gold)), "recall_holdout": rec([s for s in gold if hold[s]]),
                     "trials_with_a_gold_paper": sum(bool(sel[name][s] & gold[s]) for s in gold),
                     "papers_per_trial_median": sorted(len(sel[name][s]) for s in gold)[len(gold) // 2]}
    out["ratings"] = {str(k): v for k, v in sorted(dist.items(), key=lambda x: str(x[0]))}
    out["ratings_of_gold_papers"] = {str(k): v for k, v in sorted(gold_scores.items(), key=lambda x: str(x[0]))}
    out["not_rated"] = missing
    (DIR / "search_filter_check.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps({"dry": dry, "run": run, "score": score}[sys.argv[1]](), indent=1))

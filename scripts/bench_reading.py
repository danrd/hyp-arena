"""Reading benchmark (specs/benchmark-reading-2026-11-12.yaml) on Argon pack 16: 20 links, 400 link-abstract pairs.

    python -m scripts.bench_reading dry                          # free: calls, tokens and the price of every system
    ALLOW_PAID=1 python -m scripts.bench_reading run --system v9|v13|base_a [--limit N]
    python -m scripts.bench_reading score                        # free: metrics of every system that has a run

Systems (the same claim and the same abstracts, as our reader saw them):
  v9      verify_claim/v9 with its code checks (the reader the prospective pool was scored with);
  v13     relevance filter v2, then verify_claim/v13 in batches of 10 with an answer for every paper (scripts/reader_v12.py);
  base_a  the same model (DeepSeek V4.1 Flash), the task in one sentence (prompts/reading_baseline/v1), no reading rules, no
          code checks (no quote check, no retry, no fallback family).
Outputs: longevity-kg/reviews/argon-2026-11-12/bench_reading_<system>.json, bench_reading_score.json.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import threading
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.reread_v11 import CONFIG, items

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-12"
PRICE = {"deepseek": (0.15, 0.6), "google": (1.5, 9.0)}      # USD per M tokens off-peak (DeepSeek x2 on weekdays 01-04, 06-10 UTC)
SYSTEMS = ("v9", "v13", "base_a")


def targets() -> list[dict]:
    key = json.loads((DIR / "pack_16_key.json").read_text())
    task = {i["id"]: i for p in "ab" for i in json.loads((DIR / f"pack_16{p}_task.json").read_text())["items"]}
    want = defaultdict(dict)
    for rid, k in key.items():
        want[k["pool"]][(k["unit"], k["claim_id"])] = rid
    out = []
    for pool, ws in want.items():
        for h, as_of, card, cvs, logs in items(pool):
            for c in list(card.claims) + list(card.proposed_alternatives):
                rid = ws.get((h, c.id))
                if rid:
                    out.append({"rid": rid, "unit": h, "as_of": as_of, "card": card, "claim": c, "task": task[rid], "key": key[rid]})
    return sorted(out, key=lambda t: t["rid"])


def _claim_text(t) -> str:
    return t["task"]["claim"] + (f" (qualifiers: {', '.join(f'{a}: {b}' for a, b in t['task']['qualifiers'].items() if b)})"
                                  if t["task"].get("qualifiers") else "")


def dry() -> dict:
    """Tokens from the characters of the prompts (chars / 4) and outputs measured on earlier runs of the same readers."""
    from hyparena.card.llm import render
    ts = targets()
    est = {}
    for s in SYSTEMS:
        tin = tout = calls = 0
        for t in ts:
            papers = t["task"]["papers"]
            text = sum(len(p["title"]) + len(p["abstract"]) for p in papers)
            if s == "base_a":
                prompt = render("reading_baseline", "v1", claim=_claim_text(t), papers=papers)
                tin += len(prompt) / 4
                tout += 60 * len(papers)
                calls += 1
            elif s == "v9":
                tin += (text + 9000) / 4                              # the v9 template is about 9 000 characters
                tout += 900
                calls += 1
            else:
                tin += (sum(len(p["title"]) + 600 for p in papers) + 2500) / 4   # filter: titles and abstract starts
                tout += 25 * len(papers)
                kept = 0.45 * text                                     # the filter kept 7.8 of 20 papers on pack-9 links
                tin += (kept + 10000 * max(1, round(0.45 * len(papers) / 10))) / 4
                tout += 110 * 0.45 * len(papers)
                calls += 1 + max(1, round(0.45 * len(papers) / 10))
        usd = tin / 1e6 * PRICE["deepseek"][0] + tout / 1e6 * PRICE["deepseek"][1]
        est[s] = {"calls": calls, "tokens_in": round(tin), "tokens_out": round(tout), "usd_offpeak": round(usd, 3),
                  "usd_peak": round(2 * usd, 3)}
    return {"links": len(ts), "pairs": sum(len(t["task"]["papers"]) for t in ts), "systems": est,
            "total_usd_offpeak": round(sum(v["usd_offpeak"] for v in est.values()), 3),
            "note": "estimates; a retry or the fallback family (Gemini) on a cut reply adds to v9 and v13"}


def _records(cv: dict) -> dict:
    """PMID -> (side, quote) from a ClaimVerification dump: evidence = for, counterevidence = against."""
    out = {}
    for side, k in (("for", "evidence"), ("against", "counterevidence")):
        for r in cv.get(k) or []:
            pm = str(r.get("record_id") or r.get("linked_pmid") or "").replace("PMID:", "").strip()
            if pm and pm not in out:
                out[pm] = (side, r.get("quote") or "")
    return out


def run(system: str, limit: int = 0) -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask
    from hyparena.card.pipeline import _client
    from hyparena.card.verifier import verify_claim
    out_p = DIR / f"bench_reading_{system}.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    ts = [t for t in targets() if t["rid"] not in done][: limit or None]
    client, _ = _client(CONFIG, False, len(ts) * 12 + 20)
    lock, tok = threading.Lock(), Counter()

    def one(t):
        log: list = []
        pmids = [p["pmid"] for p in t["task"]["papers"]]
        if system == "base_a":
            value, _ = ask(client, role="reading_baseline", family="deepseek", template="reading_baseline", version="v1",
                           variables={"claim": _claim_text(t), "papers": t["task"]["papers"]}, rounds=1, log=log)
            recs = {str(x.get("pmid", "")).replace("PMID:", "").strip(): (x.get("finding"), x.get("quote") or "")
                    for x in (value or {}).get("papers") or [] if isinstance(x, dict) and x.get("finding") in ("for", "against")}
        elif system == "v9":
            cv = verify_claim(client, "deepseek", frozenset({"google"}), t["claim"], t["card"], t["as_of"], log=log,
                              fallback="google", expert_pmids=[(p, "benchmark") for p in pmids], search="fixed",
                              template_version="v9")
            recs = _records(cv.model_dump())
        else:
            from scripts import reader_v12 as rv
            from hyparena.tools import pubmed
            meta = pubmed.fetch(pmids)
            cand = [p for p in pmids if rv.rule_pass(meta.get(p, {}))]
            rows = [{"pmid": p, "title": meta[p].get("title", ""), "start": meta[p].get("abstract", "")[:600]} for p in cand]
            value, _ = ask(client, role="relevance_filter", family="deepseek", template="relevance_filter", version="v2",
                           variables={"claim": t["claim"], "qualifiers": ", ".join(f"{a}: {b}" for a, b in t["claim"].qualifiers.items() if b),
                                      "papers": rows}, validate=lambda v: [] if isinstance(v.get("papers"), list) else ['a "papers" list'],
                           rounds=2, log=log) if rows else (None, "")
            ans = {str(x.get("pmid", "")).replace("PMID:", "").strip(): x.get("own_result")
                   for x in (value or {}).get("papers") or [] if isinstance(x, dict)}
            kept = [p for p in cand if ans.get(p) in ("yes", "unsure", None)]
            recs = {}
            for i in range(0, len(kept), rv.BATCH):
                cv = verify_claim(client, "deepseek", frozenset({"google"}), t["claim"], t["card"], t["as_of"], log=log,
                                  fallback="google", expert_pmids=[(p, "benchmark") for p in kept[i:i + rv.BATCH]],
                                  search="fixed", template_version="v13", check_subgroups=False)
                recs.update({k: v for k, v in _records(cv.model_dump()).items() if k not in recs})
        with lock:
            done[t["rid"]] = {"records": {k: list(v) for k, v in recs.items()},
                              "calls": [{k: x.get(k) for k in ("template", "family", "tokens_in", "tokens_out", "error")} for x in log]}
            for x in log:
                tok[f"{x.get('family') or ''}_in"] += int(x.get("tokens_in") or 0)
                tok[f"{x.get('family') or ''}_out"] += int(x.get("tokens_out") or 0)
            out_p.write_text(json.dumps(done, ensure_ascii=False, indent=1) + "\n")

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, ts))
    usd = sum(tok[f"{f}_in"] * p[0] / 1e6 + tok[f"{f}_out"] * p[1] / 1e6 for f, p in PRICE.items())
    return {"system": system, "links_done": len(done), "this_run": len(ts), "tokens": dict(tok), "usd_offpeak": round(usd, 4)}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip().lower()


def _measures(rows: list[dict]) -> dict:
    gold_pos = [r for r in rows if r["gold"] in ("for", "against")]
    sys_pos = [r for r in rows if r["sys"] in ("for", "against")]
    hit = [r for r in gold_pos if r["sys"] == r["gold"]]
    both = [r for r in rows if r["gold"] in ("for", "against") and r["sys"] in ("for", "against")]
    cons = [r for r in rows if r["none_reason"] == "background_or_consensus"]
    return {"recall": len(hit) / len(gold_pos) if gold_pos else None, "precision": len(hit) / len(sys_pos) if sys_pos else None,
            "side": sum(r["sys"] == r["gold"] for r in both) / len(both) if both else None,
            "quote_verbatim": sum(r["verbatim"] for r in sys_pos) / len(sys_pos) if sys_pos else None,
            "consensus_recorded": sum(r["sys"] in ("for", "against") for r in cons) / len(cons) if cons else None,
            "n": {"gold_pos": len(gold_pos), "sys_pos": len(sys_pos), "hit": len(hit), "consensus": len(cons)}}


def score() -> dict:
    gold = {i["id"]: {p["pmid"]: p for p in i["papers"]} for i in json.loads((DIR / "pack_16_answer.json").read_text())["items"]}
    key = json.loads((DIR / "pack_16_key.json").read_text())
    task = {i["id"]: {p["pmid"]: p for p in i["papers"]} for p_ in "ab" for i in json.loads((DIR / f"pack_16{p_}_task.json").read_text())["items"]}
    out, rows_by = {}, {}
    for s in SYSTEMS:
        f = DIR / f"bench_reading_{s}.json"
        if not f.exists():
            continue
        res = json.loads(f.read_text())
        rows = []
        for rid, g in gold.items():
            if rid not in res:
                continue
            recs = res[rid]["records"]
            for pm, ga in g.items():
                side, quote = (recs.get(pm) or [None, ""])[:2]
                ab = _norm(task[rid][pm]["title"] + " " + task[rid][pm]["abstract"])
                rows.append({"rid": rid, "gold": ga["finding"], "sys": side or "none", "none_reason": ga.get("none_reason"),
                             "verbatim": bool(quote) and _norm(quote) in ab, "stratum": key[rid]["stratum"], "holdout": key[rid]["holdout"]})
        rows_by[s] = rows
        rng = random.Random(20261112)
        links = sorted({r["rid"] for r in rows})
        boots = defaultdict(list)
        for _ in range(2000):
            pick = [rng.choice(links) for _ in links]
            sample = [r for l in pick for r in rows if r["rid"] == l]
            m = _measures(sample)
            for k in ("recall", "precision"):
                if m[k] is not None:
                    boots[k].append(m[k])
        ci = {k: [round(sorted(v)[int(0.025 * len(v))], 3), round(sorted(v)[int(0.975 * len(v)) - 1], 3)] for k, v in boots.items()}
        out[s] = {"all": _measures(rows), "ci95": ci, "links": len(links),
                  "by_stratum": {st: _measures([r for r in rows if r["stratum"] == st]) for st in sorted({r["stratum"] for r in rows})},
                  "holdout": _measures([r for r in rows if r["holdout"]])}
    (DIR / "bench_reading_score.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dry", "run", "score"])
    ap.add_argument("--system", choices=SYSTEMS)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    r = {"dry": dry, "score": score}.get(a.cmd)
    print(json.dumps(r() if r else run(a.system, a.limit), indent=1, default=str))

"""Card benchmark (specs/benchmark-card-2026-11-12.yaml) on Argon pack 17: 60 texts, the card gold.

    python -m scripts.bench_card dry                              # free: calls, tokens and the price of each system
    ALLOW_PAID=1 python -m scripts.bench_card run --system ours|base_a [--limit N]
    python -m scripts.bench_card score                            # after Argon's answer (pack_17_answer.json); free

Systems (the same text as Argon got):
  ours    normalize_card/v11, two parses united (method v3.9), with the code checks (schema, verbatim spans, three rounds);
  base_a  the same model (Gemini 3.5 Flash), the task in one sentence and an output schema (prompts/card_baseline/v1), one
          call, no rules, no checks.
Outputs: longevity-kg/reviews/argon-2026-11-12/bench_card_<system>.json, bench_card_score.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-12"
CONFIG = "configs/v3-flash-n10.yaml"
PRICE = {"google": (1.5, 9.0), "deepseek": (0.15, 0.6)}      # USD per M tokens
SYSTEMS = ("ours", "base_a")


def texts() -> list[dict]:
    return [i for p in "ab" for i in json.loads((DIR / f"pack_17{p}_task.json").read_text())["items"]]


def dry() -> dict:
    """Tokens = characters / 4; outputs and rounds as measured on H86 (2026-11-12: 3 rounds per parse, 1.6 k tokens out)
    and on the prospective cards (most parses pass in one round): ours counted with 2 parses x 1.8 rounds."""
    from hyparena.llm.prompts import render
    ts = texts()
    tmpl = len(render("normalize_card", "v11", text="", relations="", hallmarks="", hint="", history_text=""))
    est = {}
    for s in SYSTEMS:
        if s == "ours":
            tin = sum((tmpl + len(t["text"])) / 4 * 2 * 1.8 + 600 * 2 * 0.8 for t in ts)   # retries carry the previous reply
            tout, calls = 1600 * 2 * 1.8 * len(ts), round(2 * 1.8 * len(ts))
        else:
            tin = sum(len(render("card_baseline", "v1", text=t["text"])) / 4 for t in ts)
            tout, calls = 1300 * len(ts), len(ts)
        usd = tin / 1e6 * PRICE["google"][0] + tout / 1e6 * PRICE["google"][1]
        est[s] = {"calls": calls, "tokens_in": round(tin), "tokens_out": round(tout), "usd": round(usd, 2)}
    return {"texts": len(ts), "systems": est, "total_usd": round(sum(v["usd"] for v in est.values()), 2),
            "note": "Gemini has no peak surcharge; estimates, the rounds of 'ours' vary from 1 to 3 per parse"}


def run(system: str, limit: int = 0) -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask
    from hyparena.card.normalizer import normalize_union
    from hyparena.card.pipeline import _client
    out_p = DIR / f"bench_card_{system}.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    ts = [t for t in texts() if t["id"] not in done][: limit or None]
    client, _ = _client(CONFIG, False, len(ts) * 8 + 10)
    lock, tok = threading.Lock(), Counter()

    def one(t):
        log: list = []
        if system == "ours":
            card, problems, stab = normalize_union(client, "google", t["text"], t["id"], log=log, runs=2, version="v11")
            res = {"card": card.model_dump(by_alias=True) if card else None, "problems": problems, "stability": stab}
        else:
            value, _ = ask(client, role="card_baseline", family="google", template="card_baseline", version="v1",
                           variables={"text": t["text"]}, rounds=1, log=log)
            res = {"card": value}
        res["calls"] = [{k: x.get(k) for k in ("template", "attempt", "family", "tokens_in", "tokens_out", "error")} for x in log]
        with lock:
            done[t["id"]] = res
            for x in log:
                tok[f"{x.get('family') or ''}_in"] += int(x.get("tokens_in") or 0)
                tok[f"{x.get('family') or ''}_out"] += int(x.get("tokens_out") or 0)
            out_p.write_text(json.dumps(done, ensure_ascii=False, indent=1, default=str) + "\n")

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, ts))
    usd = sum(tok[f"{f}_in"] * p[0] / 1e6 + tok[f"{f}_out"] * p[1] / 1e6 for f, p in PRICE.items())
    return {"system": system, "texts_done": len(done), "this_run": len(ts), "tokens": dict(tok), "usd": round(usd, 4)}


def score() -> dict:
    """Written after Argon's answer arrives, by the measures fixed in specs/benchmark-card-2026-11-12.yaml."""
    if not (DIR / "pack_17_answer.json").exists():
        raise SystemExit("no Argon answer yet (pack_17_answer.json)")
    raise SystemExit("score: to be written against the answer's format, by the spec's measures")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dry", "run", "score"])
    ap.add_argument("--system", choices=SYSTEMS)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    r = {"dry": dry, "score": score}.get(a.cmd)
    print(json.dumps(r() if r else run(a.system, a.limit), indent=1, default=str))

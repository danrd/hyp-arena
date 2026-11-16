"""The novelty benchmark with the high levels (specs/novelty/novelty-high-levels-2026-11-15.yaml): the working pipeline on
the 30 hypotheses of Argon pack 26 (saved cards, one date T), then our novelty N and what our search finds against Argon's.

    python -m scripts.novelty.bench_novelty dry                                   # free: the price from the confirming run of the search
    ALLOW_PAID=1 MAX_USD=3 python -m scripts.novelty.bench_novelty run [--limit N] # -> longevity-kg reviews/argon-2026-11-15/pack_26_run.json
    python -m scripts.novelty.bench_novelty score                                 # free (PubMed counts by E-utilities)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

KG = Path(__file__).resolve().parents[2].parent / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-15"
CARDS = KG / "reviews" / "argon-2026-11-13" / "bench_card_v2_ours_v17.json"
CONFIG = "configs/v3-flash-n10.yaml"
RUN = DIR / "pack_26_run.json"


def inputs() -> list[dict]:
    task = json.loads((DIR / "pack_26_task.json").read_text())["hypotheses"]
    key = json.loads((DIR / "pack_26_key.json").read_text())
    cards = json.loads(CARDS.read_text())
    return [{"id": h["id"], "T": h["T"], "text": h["text"], "card": cards[key[h["id"]]["card_pack_id"]]["card"],
             "links": len(h["chain"])} for h in task]


def dry() -> dict:
    """Per search (one link or one alternative with its reading), from the confirming run of the working search on 30 trials
    (calibration/run_*_n12.json): everything but the card stage, which is not run here (the cards are saved)."""
    usd = searches = alts = trials = 0
    for f in glob.glob(str(KG / "hypothesis_sources" / "calibration" / "run_*_n12.json")):
        for r in json.loads(Path(f).read_text()).values():
            trials += 1
            usd += sum(v["usd"] for k, v in (r.get("usage") or {}).get("stages", {}).items() if k != "card")
            searches += sum(1 for c in r.get("calls", []) if c.get("kind") == "search")
            alts += len(r["items"][0].get("v3_alternatives") or {})
    hs = inputs()
    links = sum(h["links"] for h in hs)
    expected = links + round(alts / trials * len(hs))
    per = usd / searches
    cross = 0.013 * len(hs)                       # the cross-link reading, measured per hypothesis (search manual, 5.3)
    return {"hypotheses": len(hs), "links": links, "alternatives_expected": round(alts / trials * len(hs)),
            "usd_per_search": round(per, 4), "cross_link_usd": round(cross, 2),
            "usd_offpeak": round(expected * per + cross, 2), "usd_peak": round(2 * (expected * per + cross), 2),
            "note": "an estimate: these chains have more steps than registry trials, and a step search can cost less or more than an outcome search"}


def results() -> dict:
    """Every hypothesis run so far, from the run file and its shards."""
    out = {}
    for f in sorted(DIR.glob("pack_26_run*.json")):
        if "trial" not in f.name:
            out.update(json.loads(f.read_text()))
    return out


def run(limit: int = 0, shard: str = "") -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.pipeline import run as pipeline
    k, n = (int(x) for x in shard.split("/")) if shard else (0, 1)       # --shard 1/3: every third hypothesis, its own file
    out_p = DIR / f"pack_26_run_{k}.json" if shard else RUN
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    cap, spent = float(os.environ.get("MAX_USD") or 0), sum((r.get("usage") or {}).get("total", {}).get("usd", 0) for r in done.values())
    todo = [h for i, h in enumerate(inputs()) if h["id"] not in done and (not shard or i % n == k - 1)][: limit or None]
    for h in todo:
        if cap and spent >= cap:
            print(json.dumps({"stopped": "MAX_USD", "spent": round(spent, 3)}), flush=True)
            break
        try:
            res = pipeline([h["text"]], writer="unknown", config=CONFIG, as_of=h["T"], max_calls=150, verifiers=["deepseek"],
                           cards=[h["card"]], dedup=False)
        except Exception as e:                                # e.g. PubMed answering 500: left for the next run
            print(json.dumps({"id": h["id"], "error": f"{type(e).__name__}: {str(e)[:200]}"}), flush=True)
            continue
        done[h["id"]] = res
        out_p.write_text(json.dumps(done, ensure_ascii=False, default=str))
        usd = (res.get("usage") or {}).get("total", {}).get("usd", 0)
        spent += usd
        print(json.dumps({"id": h["id"], "outcome": res["items"][0]["outcome"], "calls": res["meta"]["calls"], "usd": round(usd, 3),
                          "spent": round(spent, 3)}), flush=True)
    return {"done": len(done), "spent_usd": round(spent, 3)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["dry", "run"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shard", default="", help="run: k/n, the k-th of n parallel streams (each with its own MAX_USD)")
    a = ap.parse_args()
    print(json.dumps(dry() if a.cmd == "dry" else run(a.limit, a.shard), indent=1))

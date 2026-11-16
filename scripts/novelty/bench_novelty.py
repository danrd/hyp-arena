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


LEVELS = ["new_context", "translation", "analog", "new_mechanism", "new_combination", "new_link"]
LINK = ["new_context", "translation", "analog", "new_link"]


def _wkappa(pairs: list[tuple[int, int]], k: int) -> float | None:
    from collections import Counter
    n = len(pairs)
    if n < 2:
        return None
    a, b = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    obs = sum(abs(x - y) for x, y in pairs) / n
    exp = sum(a[x] * b[y] * abs(x - y) for x in range(k) for y in range(k)) / n / n
    return round(1 - obs / exp, 3) if exp else None


def score() -> dict:
    """Our novelty N and link levels against Argon's (pack 26), the PubMed absence counts, and how many of the papers Argon
    names per link our search handed to the reader and the reader recorded, for steps and for outcomes."""
    from collections import Counter
    from hyparena.card.models import ClaimVerification, HypothesisCard
    from hyparena.novelty import novelty_v34 as nv
    from hyparena.scoring import rules_v3 as r3
    from hyparena.scoring import rules_v32 as r32
    from hyparena.tools import compounds as cp
    r3.established_by_approval = lambda claim, card: False      # ChEMBL is not reachable here
    cp._get = lambda url: None
    gold = {h["id"]: h for h in json.loads((DIR / "pack_26_answer.json").read_text())["hypotheses"]}
    task = {h["id"]: h for h in json.loads((DIR / "pack_26_task.json").read_text())["hypotheses"]}
    key = json.loads((DIR / "pack_26_key.json").read_text())
    rows, links, papers = [], [], []
    cache_p = DIR / "pack_26_absence.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    for hid, res in sorted(results().items()):
        it = res["items"][0]
        g = gold[hid]
        reader = sorted({str(c.get("template")) for c in res.get("calls", []) if str(c.get("template", "")).startswith("verify_claim")})
        row = {"id": hid, "source": key[hid]["source"], "outcome": it["outcome"], "gold": g["novelty"], "reader": reader}
        if it["outcome"] not in ("ranked", "filtered", "known_result") or not it.get("verification"):
            rows.append(row)
            continue
        card = HypothesisCard.model_validate(it["card"])
        cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
        with r32.method():
            if hid not in cache:
                cache[hid] = nv.mechanism_absence(card, cvs, task[hid]["T"])
                cache_p.write_text(json.dumps(cache, indent=1) + "\n")
            row["N"] = nv.novelty(card, cvs, absence=cache[hid]) or "unknown"
            ours_links = nv.link_levels(card, cvs)
        row["absence"] = cache[hid]
        rows.append(row)
        given = {}
        for c in res.get("calls", []):
            if c.get("kind") == "search":
                given.setdefault(c.get("claim"), set()).update(c.get("pmids") or [])
        for cid, x in (it.get("cross_link") or {}).items():
            given.setdefault(cid, set()).update(x.get("read") or [])
        anywhere = set().union(*given.values()) if given else set()
        recorded = {cv.id: {r.record_id.replace("PMID:", "") for r in cv.evidence + cv.counterevidence} for cv in cvs}
        kinds = {c["id"]: c["type"] for c in task[hid]["chain"]}
        for gl in g["links"]:
            lid = gl["id"]
            if gl["level"] == "new_link" and lid not in cache[hid]:      # our count on a link Argon calls new (free, E-utilities)
                from hyparena.evolution.evolution_rules import pubmed_pair_count
                cl = next((c for c in card.claims if c.id == lid), None)
                cache[hid][lid] = pubmed_pair_count(cl.subject.label, cl.object.label, task[hid]["T"]) if cl else None
                cache_p.write_text(json.dumps(cache, indent=1) + "\n")
            links.append({"id": hid, "link": lid, "type": kinds.get(lid), "gold": gl["level"], "ours": ours_links.get(lid),
                          "gold_count": gl.get("pubmed_count"), "our_count": cache[hid].get(lid)})
            for p in gl.get("pmids") or []:
                papers.append({"type": kinds.get(lid), "given": str(p) in given.get(lid, set()), "anywhere": str(p) in anywhere,
                               "recorded": str(p) in recorded.get(lid, set())})
    scored = [r for r in rows if "N" in r]
    both = [(LEVELS.index(r["N"]), LEVELS.index(r["gold"])) for r in scored if r["N"] in LEVELS and r["gold"] in LEVELS]
    lk = [(LINK.index(x["ours"]), LINK.index(x["gold"])) for x in links if x["ours"] in LINK and x["gold"] in LINK]
    new = [x for x in links if x["gold"] == "new_link" and x["gold_count"] is not None and x["our_count"] is not None]

    def share(rs, k):
        return [sum(r[k] for r in rs), len(rs)]
    out = {"hypotheses": len(rows), "scored": len(scored), "outcomes": dict(Counter(r["outcome"] for r in rows)),
           "readers": dict(Counter(", ".join(r["reader"]) for r in rows)),
           "ours": dict(Counter(r["N"] for r in scored)), "gold_of_scored": dict(Counter(r["gold"] for r in scored)),
           "N": {"pairs": len(both), "wkappa": _wkappa(both, len(LEVELS)), "exact": round(sum(a == b for a, b in both) / len(both), 3) if both else None,
                 "ours_unknown": sum(r["N"] == "unknown" for r in scored),
                 "ours_farther_from_known": sum(a > b for a, b in both), "ours_nearer_the_known": sum(a < b for a, b in both),
                 "table": {f"{LEVELS[a]} / {LEVELS[b]}": c for (a, b), c in sorted(Counter(both).items())}},
           "links": {"pairs": len(lk), "wkappa": _wkappa(lk, len(LINK)), "ours": dict(Counter(str(x["ours"]) for x in links)),
                     "gold": dict(Counter(x["gold"] for x in links))},
           "absence": {"links_gold_new_with_both_counts": len(new), "same_side_of_5": sum((x["gold_count"] < 5) == (x["our_count"] < 5) for x in new),
                       "gold_new_links_we_have_no_count_for": sum(1 for x in links if x["gold"] == "new_link" and x["our_count"] is None)},
           "papers": {t: {"named_by_argon": len(ps), "given_to_the_reader_on_the_link": share(ps, "given"),
                          "given_anywhere_in_the_hypothesis": share(ps, "anywhere"), "recorded_on_the_link": share(ps, "recorded")}
                      for t in ("step", "outcome") for ps in [[p for p in papers if p["type"] == t]]},
           "rows": rows, "link_rows": links}
    (DIR / "pack_26_score.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return {k: v for k, v in out.items() if k not in ("rows", "link_rows")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["dry", "run", "score"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shard", default="", help="run: k/n, the k-th of n parallel streams (each with its own MAX_USD)")
    a = ap.parse_args()
    print(json.dumps(dry() if a.cmd == "dry" else score() if a.cmd == "score" else run(a.limit, a.shard), indent=1, ensure_ascii=False))

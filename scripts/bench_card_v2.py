"""Card benchmark against the gold under the link definitions of docs/system/card.md (card_gold_v2): Argon packs 19 (30 texts
not from a registry) and 20 (the 60 texts of pack 17 labelled again). specs/benchmark-card-2026-11-12.yaml.

    python -m scripts.bench_card_v2 dry                              # free: calls, tokens and the price
    ALLOW_PAID=1 python -m scripts.bench_card_v2 run [--limit N]     # normalize_card/v15, two parses united
    python -m scripts.bench_card_v2 score [--system ours_v15]        # free

Measures (claims matched one-to-one by phrase overlap, scripts/bench_card._match): claim recall and precision (one-to-one
and many-to-one); link kappa (premise = off the chain), also without outcomes; chain / premise agreement; main factor found
(word overlap with the gold's); population condition found; the card's main outcome among the gold's main outcomes. The
saved v13 cards of the pack 17 texts are scored on pack 20 as the earlier system.
Outputs: longevity-kg/reviews/argon-2026-11-13/bench_card_v2_<system>.json, bench_card_v2_score.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts import bench_card as b

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-13"
OLD = KG / "reviews" / "argon-2026-11-12"
CONFIG = "configs/v3-flash-n10.yaml"
PRICE = {"google": (1.5, 9.0)}           # USD per M tokens (Gemini Flash, no peak price)
VERSION = "v15"


def texts() -> list[dict]:
    out = [{"id": i["id"], "text": i["text"], "pack": 19} for i in json.loads((DIR / "pack_19_task.json").read_text())["items"]]
    out += [{"id": i["id"], "text": i["text"], "pack": 20} for p in "ab" for i in json.loads((DIR / f"pack_20{p}_task.json").read_text())["items"]]
    return out


def gold() -> dict:
    g = {i["id"]: i for i in json.loads((DIR / "pack_19_answer.json").read_text())["items"]}
    g.update({i["id"]: i for i in json.loads((DIR / "pack_20_answer.json").read_text())["items"]})
    return g


def dry() -> dict:
    tmpl = (Path(__file__).resolve().parents[1] / "hyparena" / "prompts" / "normalize_card" / f"{VERSION}.j2").read_text()
    ts = texts()
    tin = sum(len(tmpl) / 3.6 + 600 + len(t["text"]) / 3.2 for t in ts)          # template, lists, text
    # two parses; up to three rounds each; measured on v13 (pack 17): 3.85 calls and 3 640 output tokens per text
    calls, tout = 3.85 * len(ts) * 1.15, 3640 * len(ts) * 1.15
    tin_all = tin / len(ts) * calls
    usd = tin_all * PRICE["google"][0] / 1e6 + tout * PRICE["google"][1] / 1e6
    return {"texts": len(ts), "calls_est": round(calls), "tokens_in_est": round(tin_all), "tokens_out_est": round(tout),
            "usd_est": round(usd, 2), "usd_per_text": round(usd / len(ts), 3), "model": "Gemini Flash (google family), no peak price"}


def run(limit: int = 0, ids: str = "", runs: int = 1) -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.normalizer import normalize_union
    from hyparena.card.pipeline import _client
    out_p = DIR / f"bench_card_v2_ours_{VERSION}.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    want = set(ids.split(",")) if ids else None
    ts = [t for t in texts() if t["id"] not in done and (want is None or t["id"] in want)][: limit or None]
    client, _ = _client(CONFIG, False, len(ts) * 10 + 10)
    lock, tok = threading.Lock(), Counter()

    def one(t):
        log: list = []
        card, problems, stab = normalize_union(client, "google", t["text"], t["id"], log=log, runs=runs, version=VERSION)
        res = {"card": card.model_dump(by_alias=True) if card else None, "problems": problems, "stability": stab,
               "calls": [{k: x.get(k) for k in ("at", "template", "attempt", "family", "model", "seconds", "tokens_in", "tokens_out", "error")} for x in log]}
        with lock:
            done[t["id"]] = res
            for x in log:
                tok["in"] += int(x.get("tokens_in") or 0)
                tok["out"] += int(x.get("tokens_out") or 0)
            out_p.write_text(json.dumps(done, ensure_ascii=False, indent=1, default=str) + "\n")

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, ts))
    usd = tok["in"] * PRICE["google"][0] / 1e6 + tok["out"] * PRICE["google"][1] / 1e6
    return {"texts_done": len(done), "this_run": len(ts), "tokens": dict(tok), "usd": round(usd, 3)}


SYN = {"old": "aged", "older": "aged", "elderly": "aged", "ageing": "aged", "aging": "aged", "geriatric": "aged",
       "mice": "mouse", "murine": "mouse", "rats": "rat", "humans": "human", "people": "human", "persons": "human",
       "women": "woman", "men": "man"}


def _toks(s: str) -> set:
    """Content words (first 6 letters) with age and species synonyms on one word: "old mouse" = "aged mice"."""
    words = [SYN.get(w, w) for w in re.findall(r"[a-z0-9]{3,}", (s or "").lower())]
    return {w[:6] for w in words} - {"the", "and", "with", "adults", "adult"}


def _ov(a: str, b_: str) -> bool:
    ta, tb = _toks(a), _toks(b_)
    return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.5


def _gold_label(c: dict) -> str:
    return "premise" if c.get("part") == "premise" else (c.get("link") or "premise")


def _three(label: str) -> str:
    """outcome / step / premise: the classes the method reads (method v3.10)."""
    return label if label in ("outcome", "premise") else "step"


def _sys_claims(card: dict, v15: bool) -> list[dict]:
    out = []
    for c in card.get("claims") or []:
        lab = "premise" if (c.get("part") == "premise" or not c.get("link")) else c["link"]
        out.append({"phrase": c.get("source_span") or "", "lab": lab, "primary": bool(c.get("primary")),
                    "obj": f"{c['object']['label']} {(c.get('qualifiers') or {}).get('measure', '')}"})
    return out


def _match_label(sc: list[dict], gc: list[dict]) -> list[tuple[dict, dict]]:
    """One-to-one by phrase overlap (bench_card._match), then the claims left over by their labels: the system claim's object
    and measure against the gold claim's object, half of the shorter one's content words (synonyms on one word). The same
    claim anchored to another sentence of the text (the Primary outcomes line against the aims) is then found."""
    pairs = b._match(sc, gc)
    used_s, used_g = {id(s) for s, _ in pairs}, {id(g_) for _, g_ in pairs}
    cand = []
    for s in sc:
        if id(s) in used_s:
            continue
        for g_ in gc:
            if id(g_) in used_g:
                continue
            ta, tb = _toks(s["obj"]), _toks(g_.get("object", ""))
            if ta and tb:
                ov = len(ta & tb) / min(len(ta), len(tb))
                if ov >= 0.5:
                    cand.append((ov, id(s), id(g_), s, g_))
    for ov, i_s, i_g, s, g_ in sorted(cand, key=lambda x: -x[0]):
        if i_s not in used_s and i_g not in used_g:
            used_s.add(i_s); used_g.add(i_g); pairs.append((s, g_))
    return pairs


def score_system(cards: dict, gold_: dict, v15: bool) -> dict:
    pairs, rows = [], Counter()
    for tid, g in gold_.items():
        card = (cards.get(tid) or {}).get("card")
        if not card:
            continue
        sc, gc = _sys_claims(card, v15), [dict(c, phrase=c.get("phrase") or "") for c in g["claims"]]
        m = b._match(sc, gc)
        pairs += [(_gold_label(gl), s["lab"]) for s, gl in m]
        rows["texts"] += 1; rows["gold"] += len(gc); rows["sys"] += len(sc); rows["matched"] += len(m)
        rows["matched_label"] += len(_match_label(sc, gc))
        ok = lambda a, c: (ta := b._toks(a["phrase"])) and (tb := b._toks(c["phrase"])) and len(ta & tb) / min(len(ta), len(tb)) >= 0.5
        rows["gold_found_m2o"] += sum(any(ok(s, gl) for s in sc) for gl in gc)
        rows["sys_right_m2o"] += sum(any(ok(s, gl) for gl in gc) for s in sc)
        mains = [o["measure"] for o in g.get("outcomes") or [] if o.get("main")]
        prim = [s for s in sc if s["primary"]]
        rows["main_outcome_n"] += 1
        rows["main_outcome_ok"] += bool(prim and any(_ov(prim[0]["obj"], x) for x in mains))
        if v15:
            mf = (card.get("main_factor") or {}).get("label", "")
            rows["main_factor_ok"] += _ov(mf, (g.get("main_factor") or {}).get("name", ""))
        gcond = (g.get("population") or {}).get("condition") or ""
        if gcond:
            rows["condition_n"] += 1
            pop = card["pico"]["population"]
            rows["condition_ok"] += _ov(f"{pop.get('condition', '')} {pop.get('label', '')}", gcond)
    r = lambda a, c: round(rows[a] / rows[c], 3) if rows[c] else None
    return {"texts": rows["texts"], "recall": r("matched", "gold"), "precision": r("matched", "sys"),
            "recall_m2o": r("gold_found_m2o", "gold"), "precision_m2o": r("sys_right_m2o", "sys"),
            "recall_phrase_or_label": r("matched_label", "gold"), "precision_phrase_or_label": r("matched_label", "sys"),
            "link_kappa": b._kappa(pairs), "link_kappa_without_outcome": b._kappa([p for p in pairs if "outcome" not in p]),
            "kappa_3": b._kappa([(_three(a), _three(c)) for a, c in pairs]),
            "agree_3": round(sum(_three(a) == _three(c) for a, c in pairs) / len(pairs), 3) if pairs else None,
            "chain_premise_agree": round(sum((a == "premise") == (c == "premise") for a, c in pairs) / len(pairs), 3) if pairs else None,
            "by_gold": {l: f"{sum(c == l for a, c in pairs if a == l)}/{sum(a == l for a, _ in pairs)}"
                        for l in ("delivery", "engagement", "pathway", "effect", "outcome", "premise")},
            "main_outcome": r("main_outcome_ok", "main_outcome_n"), "main_factor": r("main_factor_ok", "texts") if v15 else None,
            "population_condition": r("condition_ok", "condition_n")}


def score() -> dict:
    g = gold()
    out = {}
    f = DIR / f"bench_card_v2_ours_{VERSION}.json"
    if f.exists():
        cards = json.loads(f.read_text())
        out[f"ours_{VERSION}"] = {"all": score_system(cards, g, True),
                                   "pack19": score_system(cards, {k: v for k, v in g.items() if k.startswith("N")}, True),
                                   "pack20": score_system(cards, {k: v for k, v in g.items() if k.startswith("P")}, True)}
    key20 = json.loads((DIR / "pack_20_key.json").read_text())
    v13 = json.loads((OLD / "bench_card_ours_v13_dedup.json").read_text())
    out["ours_v13_pack20"] = score_system({pid: v13.get(k["pack17_id"]) for pid, k in key20.items()},
                                          {k: v for k, v in g.items() if k.startswith("P")}, False)
    (DIR / "bench_card_v2_score.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dry", "run", "score"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    print(json.dumps({"dry": dry, "score": score}[a.cmd]() if a.cmd != "run" else run(a.limit, a.ids, a.runs), indent=1))

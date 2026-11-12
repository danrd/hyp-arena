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
SYSTEMS = ("ours", "ours_v12", "ours_v13", "ours_v13_dedup", "ours_v14", "base_a")
NORMALIZE = {"ours": "v11", "ours_v12": "v12", "ours_v13": "v13", "ours_v13_dedup": "v13", "ours_v14": "v14"}


def texts() -> list[dict]:
    return [i for p in "ab" for i in json.loads((DIR / f"pack_17{p}_task.json").read_text())["items"]]


def dry() -> dict:
    """Tokens = characters / 4; outputs and rounds as measured on H86 (2026-11-12: 3 rounds per parse, 1.6 k tokens out)
    and on the prospective cards (most parses pass in one round): ours counted with 2 parses x 1.8 rounds."""
    from hyparena.llm.prompts import render
    ts = texts()
    tmpl = len(render("normalize_card", "v12", text="", relations="", hallmarks="", hint="", history_text=""))
    est = {}
    for s in SYSTEMS:
        if s in NORMALIZE:
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
        if system in NORMALIZE:
            card, problems, stab = normalize_union(client, "google", t["text"], t["id"], log=log, runs=2,
                                                   version=NORMALIZE[system])
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


def _toks(s: str) -> set:
    return set(re.findall(r"\w+", unicodedata.normalize("NFKC", s or "").lower()))


def _match(sys_claims: list[dict], gold_claims: list[dict]) -> list[tuple[dict, dict]]:
    """One-to-one by phrase overlap: shared words / words of the shorter phrase >= 0.5, best pairs first."""
    pairs = []
    for a in sys_claims:
        for b in gold_claims:
            ta, tb = _toks(a["phrase"]), _toks(b["phrase"])
            if ta and tb:
                ov = len(ta & tb) / min(len(ta), len(tb))
                if ov >= 0.5:
                    pairs.append((ov + len(ta & tb) / len(ta | tb), id(a), id(b), a, b))   # ties: the closer phrase first
    used_a, used_b, out = set(), set(), []
    for ov, ia, ib, a, b in sorted(pairs, key=lambda x: -x[0]):
        if ia not in used_a and ib not in used_b:
            used_a.add(ia), used_b.add(ib), out.append((a, b))
    return out


def _m2o(sys_claims: list[dict], gold_claims: list[dict]) -> tuple[int, int]:
    """Many-to-one (added 2026-11-12 AFTER the first run, a diagnosis of granularity, not the spec's measure): a system claim is
    right when its phrase shares half of the shorter one's words with some gold claim; a gold claim is found when at least one
    system claim does. Returns (gold claims found, system claims right)."""
    ok = lambda a, b: (ta := _toks(a["phrase"])) and (tb := _toks(b["phrase"])) and len(ta & tb) / min(len(ta), len(tb)) >= 0.5
    return sum(any(ok(a, g) for a in sys_claims) for g in gold_claims), sum(any(ok(a, g) for g in gold_claims) for a in sys_claims)


def _sys_view(system: str, card: dict) -> dict:
    """The system's card in the gold's terms."""
    if not card:
        return {"claims": [], "interventions": [], "comparator": None, "design": None}
    if system in NORMALIZE:
        claims = [{"phrase": c.get("source_span") or "", "link": c.get("link") or "none", "primary": c.get("role") == "outcome",
                   "stated_as": c.get("stated_as"), "level": c.get("level")}
                  for c in card.get("claims") or []]
        ints = [(x.get("label") or "") + " " + (x.get("span") or "") for x in card["pico"].get("intervention") or []]
        comp = {"placebo": "placebo", "sham": "sham", "active": "active", "usual_care": "usual_care",
                "no_intervention": "no_intervention", "untreated": "no_intervention", "standard_care": "usual_care",
                "active_drug": "active", "monotherapy": "active", "other": "other", "unknown": "none_stated"}.get(
                    card["pico"]["comparator"].get("type"), "other")
        design = {"rct": "randomised", "cluster_rct": "randomised", "single_arm": "single_arm", "pilot": "not_stated",
                  "observational": "observational", "unknown": "not_stated", "other": "not_stated"}.get(card["decisive_experiment"].get("design"))
        return {"claims": claims, "interventions": ints, "comparator": comp, "design": design,
                "unanchored": card.get("unanchored") or []}
    claims = [{"phrase": c.get("phrase") or "", "link": c.get("link") or "none", "primary": False} for c in card.get("claims") or []
              if isinstance(c, dict)]
    ints = [(x.get("name") or "") for x in card.get("interventions") or [] if isinstance(x, dict)]
    comp = str((card.get("comparator") or {}).get("kind") or "none_stated").lower()
    design = str((card.get("experiment") or {}).get("design") or "not_stated").lower()
    design = "randomised" if "random" in design else design
    return {"claims": claims, "interventions": ints, "comparator": comp, "design": design}


def _kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    labs = sorted({x for p in pairs for x in p})
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pa, pb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(pa[l] * pb[l] for l in labs) / n / n
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


def _measures(rows: list[dict]) -> dict:
    tot = lambda k: sum(r[k] for r in rows)
    m = {"claim_recall": tot("hit") / tot("gold") if tot("gold") else None,
         "claim_precision": tot("hit") / tot("sys") if tot("sys") else None,
         "step_recall": tot("hit_step") / tot("gold_step") if tot("gold_step") else None,
         "step_precision": tot("hit_step") / tot("sys_step") if tot("sys_step") else None,
         "invented_steps_in_texts_without_steps": sum(r["sys_step"] for r in rows if r["gold_step"] == 0),
         "m2o_recall_post_hoc": tot("m2o_found") / tot("gold") if tot("gold") else None,
         "m2o_precision_post_hoc": tot("m2o_right") / tot("sys") if tot("sys") else None,
         "known_steps_without_link": tot("known_unlinked"),
         "link_kappa": _kappa([p for r in rows for p in r["link_pairs"]]),
         "stated_as_kappa": _kappa([p for r in rows for p in r.get("stated_pairs", [])]),
         "level_kappa": _kappa([p for r in rows for p in r.get("level_pairs", [])]),
         "background_listed_as_intervention": (tot("bg_as_int") / tot("bg")) if tot("bg") else None,
         "comparator_agree": sum(r["comp_ok"] for r in rows) / len(rows) if rows else None,
         "design_agree": sum(r["design_ok"] for r in rows) / len(rows) if rows else None,
         "n": {"texts": len(rows), "gold_claims": tot("gold"), "sys_claims": tot("sys"), "gold_steps": tot("gold_step")}}
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()}


def dedup_saved() -> dict:
    """Free: the saved v13 cards with normalizer.dedupe_claims applied after the fact (what the union would have kept)."""
    from hyparena.card.models import HypothesisCard
    from hyparena.card.normalizer import dedupe_claims, derive_roles
    res = json.loads((DIR / "bench_card_ours_v13.json").read_text())
    out, removed = {}, 0
    for tid, v in res.items():
        card = HypothesisCard.model_validate(v["card"])
        gone = dedupe_claims(card)
        derive_roles(card)
        removed += len(gone)
        out[tid] = {**v, "card": card.model_dump(by_alias=True), "deduplicated": gone, "calls": []}
    (DIR / "bench_card_ours_v13_dedup.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str) + "\n")
    return {"texts": len(out), "claims_removed": removed}


def score() -> dict:
    """By the measures of specs/benchmark-card-2026-11-12.yaml (written before Argon's answer and before any run)."""
    gold = {i["id"]: i for i in json.loads((DIR / "pack_17_answer.json").read_text())["items"]}
    key = json.loads((DIR / "pack_17_key.json").read_text())
    out = {}
    for s in SYSTEMS:
        f = DIR / f"bench_card_{s}.json"
        if not f.exists():
            continue
        res = json.loads(f.read_text())
        rows = []
        for tid, g in gold.items():
            if tid not in res:
                continue
            sv = _sys_view(s, res[tid].get("card"))
            gc = [c for c in g.get("claims") or [] if c.get("link") != "none"]
            pairs = _match(sv["claims"], gc)
            step = lambda c: c.get("link") not in ("outcome", "none")
            bg = [b.get("phrase") or b.get("name") or "" for b in g.get("background") or [] if isinstance(b, dict)] + \
                 [b for b in g.get("background") or [] if isinstance(b, str)]
            gcomp = str((g.get("comparator") or {}).get("kind") or "none_stated")
            gdes = str((g.get("experiment") or {}).get("design") or "not_stated")
            rows.append({"tid": tid, "group": key[tid]["group"], "holdout": key[tid]["holdout"],
                         "gold": len(gc), "sys": len(sv["claims"]), "hit": len(pairs),
                         "gold_step": sum(step(c) for c in gc), "sys_step": sum(step(c) for c in sv["claims"]),
                         "hit_step": sum(1 for a, b in pairs if step(a) and step(b)),
                         "link_pairs": [(a["link"], b["link"]) for a, b in pairs],
                         "m2o_found": _m2o(sv["claims"], gc)[0], "m2o_right": _m2o(sv["claims"], gc)[1],
                         "known_unlinked": sum(1 for c in sv["claims"] if c.get("stated_as") == "known" and c["link"] == "none"),
                         "stated_pairs": [(a.get("stated_as"), b.get("stated_as")) for a, b in pairs if a.get("stated_as")],
                         "level_pairs": [(a.get("level"), b.get("level")) for a, b in pairs if a.get("level")],
                         "bg": len(bg), "bg_as_int": sum(1 for b in bg if any(len(_toks(b) & _toks(i)) / max(1, min(len(_toks(b)), len(_toks(i)))) >= 0.5
                                                                             for i in sv["interventions"])),
                         "comp_ok": sv["comparator"] == gcomp, "design_ok": (sv["design"] or "not_stated") == gdes})
        out[s] = {"all": _measures(rows),
                  "by_group": {gr: _measures([r for r in rows if r["group"] == gr]) for gr in sorted({r["group"] for r in rows})},
                  "holdout": _measures([r for r in rows if r["holdout"]])}
        if s in NORMALIZE:
            un = Counter(u.split("[")[0] for tid in res for u in (res[tid].get("card") or {}).get("unanchored") or [])
            out[s]["unanchored_fields"] = dict(un)
    (DIR / "bench_card_score.json").write_text(json.dumps(out, indent=1) + "\n")
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dry", "run", "score", "dedup"])
    ap.add_argument("--system", choices=SYSTEMS)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    r = {"dry": dry, "score": score, "dedup": dedup_saved}.get(a.cmd)
    print(json.dumps(r() if r else run(a.system, a.limit), indent=1, default=str))

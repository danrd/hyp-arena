"""Do plain code-built queries (PubMed's automatic term mapping, no field tags) find the search gold the model-written
queries miss? Free (E-utilities only), on Argon pack 18.

    python -m scripts.search_simple_check     # longevity-kg/reviews/argon-2026-11-12/search_simple_check.json

Per trial, from the saved card: A = intervention AND outcome (each outcome claim's measure or object); B = intervention AND
population; C = the intervention alone. Untagged terms, so PubMed maps them to MeSH headings and their entry terms itself.
Each query is cut at 20, 50 and 100 by relevance before T; recall against the gold alone and united with the saved
model-written queries (top 20 each, as scripts/mesh_search_check.py).
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

from scripts.bench_search import gold_answer, valid
from scripts.search_misses import _esearch

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-12"
CAL = KG / "hypothesis_sources" / "calibration"
CACHE = DIR / "search_simple_cache.json"
STOP = {"unknown", "human", "humans", "mouse", "mice", ""}


def _clean(s: str) -> str:
    s = re.sub(r"\([^)]*\)", " ", s or "")
    return re.sub(r"[^A-Za-z0-9+\- ]+", " ", s).strip()


def variants(card: dict) -> dict:
    p = card.get("pico") or {}
    ints = [_clean(i.get("label", "")) for i in (p.get("intervention") or [])[:1]]
    ints = [i for i in ints if i.lower() not in STOP]
    outs = []
    for c in card.get("claims") or []:
        if c.get("link") == "outcome" or c.get("role") == "outcome":
            m = (c.get("qualifiers") or {}).get("measure") or c["object"]["label"]
            if _clean(m).lower() not in STOP:
                outs.append(_clean(m))
    pop = _clean((p.get("population") or {}).get("label", ""))
    out = {"A_intervention_outcome": [f"({i}) AND ({o})" for i in ints for o in dict.fromkeys(outs)],
           "B_intervention_population": [f"({i}) AND ({pop})" for i in ints] if pop.lower() not in STOP else [],
           "C_intervention": [f"({i})" for i in ints]}
    return out


def run() -> dict:
    ans = gold_answer()
    key = json.loads((DIR / "pack_18_key.json").read_text())
    pm = json.loads((DIR / "pack_18_pubmed.json").read_text())
    runs = {}
    for f in sorted(glob.glob(str(CAL / "run_*_v10.json"))):
        runs.update(json.loads(Path(f).read_text()))
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    old = json.loads((DIR / "mesh_search_cache.json").read_text())
    rows = {}
    try:
        for sid, g in sorted(ans.items()):
            k = key[sid]; T = k["T"] if len(k["T"]) > 7 else k["T"] + "-28"
            r = runs[k["unit"]]; card = r["items"][0].get("card") or {}
            gold = {p["pmid"] for p in g["papers"] if valid(pm, p["pmid"]) and (pm[p["pmid"]].get("earliest") or "") <= T}
            base = set()
            for c in r["calls"]:
                if c.get("kind") == "search_plan":
                    for q in c.get("guarded") or c.get("model_queries") or []:
                        base |= set(old.get(f"{T}|{q}", {}).get("ids", [])[:20])
            row = {"gold": sorted(gold), "base": sorted(base & gold), "base_n": len(base), "v": {}}
            for name, qs in variants(card).items():
                hits = [_esearch(q, T, cache) for q in qs]
                row["v"][name] = {str(n): sorted(set().union(*[set(h["ids"][:n]) for h in hits] or [set()])) for n in (20, 50, 100)}
                row["v"][name]["count"] = [h["count"] for h in hits]
            rows[sid] = row
            print(sid, len(gold), len(row["base"]), {n: len(set(v["50"]) & gold) for n, v in row["v"].items()}, flush=True)
    finally:
        CACHE.write_text(json.dumps(cache) + "\n")
    n = sum(len(r["gold"]) for r in rows.values())
    med = lambda xs: sorted(xs)[len(xs) // 2]
    out = {"gold_papers": n, "base": {"recall": round(sum(len(r["base"]) for r in rows.values()) / n, 3), "returned_median": med([r["base_n"] for r in rows.values()])}}
    names = list(next(iter(rows.values()))["v"])
    for name in names + ["A+B+C"]:
        for cut in ("20", "50", "100"):
            alone = add = 0; sizes = []
            for r in rows.values():
                gold = set(r["gold"])
                ids = set().union(*[set(r["v"][x][cut]) for x in (names if name == "A+B+C" else [name])])
                alone += len(ids & gold); add += len((ids | set(r["base"])) & gold); sizes.append(len(ids))
            out[f"{name}@{cut}"] = {"recall_alone": round(alone / n, 3), "recall_with_base": round(add / n, 3), "returned_median": med(sizes)}
    out["empty_queries"] = {name: sum(1 for r in rows.values() if not any(r["v"][name]["count"])) for name in names}
    (DIR / "search_simple_check.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

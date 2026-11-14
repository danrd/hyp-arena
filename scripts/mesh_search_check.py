"""Do MeSH synonyms and shorter queries find more of the search gold? Free (PubMed E-utilities only), on Argon pack 18.

    python -m scripts.mesh_search_check     # longevity-kg/reviews/argon-2026-11-12/mesh_search_check.json

The saved model-written queries of the 30 calibration trials (run_*_v10.json, each claim's guarded queries) are re-run in
three variants, each query cut to its top 20 by relevance before T (as the pipeline does), the union per trial compared with
the gold papers (valid, on or before T):
  original   the saved queries as they are (re-run today, so PubMed's drift is the same for all variants);
  synonyms   every AND block that names an entity of the card (intervention, population, outcome, a claim's object or
             measure) gets the entity's MeSH heading ([mh]) and entry terms ([tiab]) as OR alternatives (hyparena.tools.mesh:
             an exact descriptor or entry term, else nothing);
  synonyms_3 as synonyms, and a query of more than three blocks keeps the intervention and outcome blocks (design filters and
             population blocks dropped first), as search_queries/v2 asks.
Not run: the citation step and the keyword fallback (the same in every variant), the reading.
"""
from __future__ import annotations

import glob
import json
import re
from collections import defaultdict
from pathlib import Path

from hyparena.tools import mesh
from scripts.bench_search import gold_answer, valid
from scripts.search_misses import _blocks, _esearch, _kind

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-12"
CAL = KG / "hypothesis_sources" / "calibration"
CACHE = DIR / "mesh_search_cache.json"


def _entities(card: dict) -> list[str]:
    p = card.get("pico") or {}
    labs = [i.get("label", "") for i in p.get("intervention") or []] + [(p.get("population") or {}).get("label", ""),
                                                                       (p.get("outcome") or {}).get("metric", "")]
    for c in card.get("claims") or []:
        labs += [c["object"]["label"], (c.get("qualifiers") or {}).get("measure", "")]
    return [x for x in dict.fromkeys(labs) if x and x.lower() not in ("unknown", "human", "humans", "mouse", "mice")]


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z-]{3,}", (s or "").lower())}


def _expand(q: str, ents: dict) -> str:
    out = []
    for b in _blocks(q):
        add = []
        for lab, syn in ents.items():
            if syn and _words(lab) & _words(b):
                add += [f'"{syn[0]}"[mh]'] + [f'"{t}"[tiab]' for t in syn[1:]]
        add = [a for a in dict.fromkeys(add) if a.lower() not in b.lower()]
        inner = b[1:-1] if b.startswith("(") and b.endswith(")") else b
        out.append(f"({inner} OR {' OR '.join(add)})" if add else b)
    return " AND ".join(out)


def _short(q: str, card: dict) -> str:
    bl = _blocks(q)
    if len(bl) <= 3:
        return q
    kinds = [_kind(b, card) for b in bl]
    order = sorted(range(len(bl)), key=lambda i: {"intervention": 0, "outcome_or_other": 1, "population": 2, "design_filter": 3}[kinds[i]])
    keep = sorted(order[:3])
    return " AND ".join(bl[i] for i in keep)


def run() -> dict:
    ans = gold_answer()
    key = json.loads((DIR / "pack_18_key.json").read_text())
    pm = json.loads((DIR / "pack_18_pubmed.json").read_text())
    runs = {}
    for f in sorted(glob.glob(str(CAL / "run_*_v10.json"))):
        runs.update(json.loads(Path(f).read_text()))
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    found = defaultdict(lambda: defaultdict(set)); gold = {}
    try:
        for sid, g in sorted(ans.items()):
            k = key[sid]; T = k["T"] if len(k["T"]) > 7 else k["T"] + "-28"
            r = runs[k["unit"]]; card = r["items"][0].get("card") or {}
            gold[sid] = {p["pmid"] for p in g["papers"] if valid(pm, p["pmid"]) and (pm[p["pmid"]].get("earliest") or "") <= T}
            ents = {lab: mesh.synonyms(lab) for lab in _entities(card)}
            for c in r["calls"]:
                if c.get("kind") != "search_plan":
                    continue
                for q in c.get("guarded") or c.get("model_queries") or []:
                    qs = {"original": q, "synonyms": _expand(q, ents)}
                    qs["synonyms_3"] = _short(qs["synonyms"], card)
                    for v, qq in qs.items():
                        found[v][sid] |= set(_esearch(qq, T, cache)["ids"][:20])
            print(sid, {v: len(found[v][sid] & gold[sid]) for v in found}, len(gold[sid]), flush=True)
    finally:
        CACHE.write_text(json.dumps(cache) + "\n")
    n = sum(len(x) for x in gold.values())
    out = {v: {"recall": round(sum(len(found[v][s] & gold[s]) for s in gold) / n, 3),
               "trials_with_a_gold_paper": sum(bool(found[v][s] & gold[s]) for s in gold),
               "returned_per_trial_median": sorted(len(found[v][s]) for s in gold)[len(gold) // 2]} for v in found}
    out["gold_papers"] = n
    (DIR / "mesh_search_check.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

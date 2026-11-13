"""Pack 20 against pack 17 (the same 60 texts, the outside reader under the old and the new link definitions) and our saved
v13 cards against the new gold. Free, no call.

    python -m scripts.relabel_compare     # longevity-kg/reviews/argon-2026-11-13/relabel_compare.json

Claims are matched one-to-one by phrase overlap (scripts/bench_card._match). Labels: the chain links, and "premise" for
everything off the chain (old: population_state or none; new: part premise). Measures: Cohen's kappa of the link, the
agreement per gold class, kappa without outcomes (the middle links), and the claim recall / precision of our cards.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts import bench_card as b

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
OLD = KG / "reviews" / "argon-2026-11-12"
NEW = KG / "reviews" / "argon-2026-11-13"
LABELS = ("delivery", "engagement", "pathway", "effect", "outcome", "premise")


def _lab_old(c: dict) -> str:
    l = c.get("link") or "none"
    return "premise" if l in ("none", "population_state") else l


def _lab_new(c: dict) -> str:
    return "premise" if c.get("part") == "premise" else (c.get("link") or "premise")


def _pairs_table(pairs: list[tuple[str, str]]) -> dict:
    return {"n": len(pairs), "kappa": b._kappa(pairs), "kappa_without_outcome": b._kappa([p for p in pairs if "outcome" not in p]),
            "agree": round(sum(a == c for a, c in pairs) / len(pairs), 3) if pairs else None,
            "by_first": {l: f"{sum(c == l for a, c in pairs if a == l)}/{sum(a == l for a, _ in pairs)}" for l in LABELS},
            "confusion": {f"{a} -> {c}": n for (a, c), n in Counter(pairs).most_common() if a != c}}


def run() -> dict:
    key = json.loads((NEW / "pack_20_key.json").read_text())
    new = {i["id"]: i for i in json.loads((NEW / "pack_20_answer.json").read_text())["items"]}
    old = {i["id"]: i for i in json.loads((OLD / "pack_17_answer.json").read_text())["items"]}
    ours = json.loads((OLD / "bench_card_ours_v13_dedup.json").read_text())
    argon_pairs, ours_pairs, ours_old_pairs, counts = [], [], [], Counter()
    for pid, n in new.items():
        kid = key[pid]["pack17_id"]
        ncl = [dict(c, phrase=c.get("phrase") or "") for c in n["claims"]]
        ocl = [dict(c, phrase=c.get("phrase") or "") for c in old[kid]["claims"]]
        argon_pairs += [(_lab_old(o), _lab_new(x)) for o, x in b._match(ocl, ncl)]
        counts["new_claims"] += len(ncl); counts["old_claims"] += len(ocl)
        card = ours.get(kid, {}).get("card")
        if card:
            sysc = [{"phrase": c.get("source_span") or "", "link": c.get("link") or "none"} for c in card.get("claims") or []]
            m = b._match(sysc, ncl)
            ours_pairs += [(_lab_new(g), "premise" if s["link"] == "none" else s["link"]) for s, g in m]
            ours_old_pairs += [(_lab_old(g), "premise" if s["link"] == "none" else s["link"]) for s, g in b._match(sysc, ocl)]
            counts["ours_claims"] += len(sysc); counts["ours_matched_new"] += len(m)
    out = {"counts": dict(counts),
           "argon_old_vs_new": _pairs_table(argon_pairs),
           "ours_v13_vs_new_gold": _pairs_table(ours_pairs),
           "ours_v13_vs_old_gold": _pairs_table(ours_old_pairs),
           "ours_recall_new": round(counts["ours_matched_new"] / counts["new_claims"], 3),
           "ours_precision_new": round(counts["ours_matched_new"] / counts["ours_claims"], 3)}
    (NEW / "relabel_compare.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

"""Argon pack 28 scored (specs/alternatives/design-rule-2026-11-16.yaml, universal_rule): the threat lists per system, the
design features the outside reader's verdicts rest on, the card's experiment against those features, and a code verdict
by system from (a) the features the outside reader extracted (an upper bound of a rule) and (b) the card's own fields.
Free: no model call; the PMIDs of the literature are checked against PubMed (E-utilities).

    python -m scripts.alternatives.pack28_score     # -> longevity-kg reviews/argon-2026-11-16/pack_28_score.json
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from scripts.alternatives.design_rule import ORDER, wkappa

KG = Path(__file__).resolve().parents[2].parent / "longevity-kg"
D = KG / "reviews" / "argon-2026-11-16"
CARDS = KG / "reviews" / "argon-2026-11-13" / "bench_card_v2_ours_v17.json"
LISTS = {
    "human": {"practice", "regression", "assessor", "expectation", "attention", "selection", "cointervention", "multiplicity"},
    "animal": {"allocation", "assessor", "attrition", "handling", "housing", "sex_strain_age", "multiplicity"},
    "cells": {"batch", "off_target", "vehicle", "culture_artefact", "line_identity", "multiplicity"},
    "data_analysis": {"confounding", "reverse_causation", "selection", "measurement", "multiplicity"},
}


def verdict(threat: str, f: dict) -> str:
    """What the stated experiment does to a methodological threat, from its design features (True when the text states
    the feature): control, randomised allocation, blinding, replication, a specificity control."""
    ctrl, rand, blind, rep, spec = (f.get(k) for k in ("concurrent_control", "randomised", "blinding", "replication", "specificity_control"))
    if threat in ("practice", "regression"):
        return "eliminated" if ctrl and rand else "weakened" if ctrl else "unchanged"
    if threat == "assessor":
        return "eliminated" if blind else "unchanged"
    if threat == "expectation":
        return "eliminated" if blind and ctrl else "weakened" if blind or ctrl else "unchanged"
    if threat == "attention":
        return "weakened" if ctrl else "unchanged"
    if threat in ("selection", "cointervention", "allocation"):
        return "eliminated" if rand and threat == "allocation" else "weakened" if rand else "unchanged"
    if threat in ("handling", "vehicle"):
        return "eliminated" if ctrl else "unchanged"
    if threat == "off_target":
        return "eliminated" if spec else "unchanged"
    if threat == "batch":
        return "weakened" if rep else "unchanged"
    return "unchanged"      # multiplicity, culture artefact, line identity, housing, one sex or strain, confounding, attrition


def features_of_argon(item: dict) -> dict:
    f = item.get("design_features") or {}
    alloc = (f.get("allocation") or "").lower()
    return {"concurrent_control": bool(f.get("concurrent_control")), "randomised": "random" in alloc or "рандом" in alloc,
            "blinding": bool(f.get("blinding")), "replication": bool(f.get("replication")),
            "specificity_control": bool(f.get("specificity_control"))}


def features_of_card(card: dict) -> dict:
    e = card.get("decisive_experiment") or {}
    ctrl = str(e.get("control") or "unknown") not in ("unknown", "none", "")
    return {"concurrent_control": ctrl, "randomised": e.get("design") == "rct", "blinding": False, "replication": False,
            "specificity_control": False}


def _system(s: str) -> str:
    return {"mouse": "animal", "rat": "animal", "worm": "animal", "fly": "animal", "yeast": "cells", "in_vitro": "cells"}.get(s, s)


def main() -> dict:
    ans = json.loads((D / "pack_28_answer.json").read_text())["items"]
    key = json.loads((D / "pack_28_key.json").read_text())
    cards = json.loads(CARDS.read_text())
    rows, lists, rests, card_vs = [], defaultdict(Counter), defaultdict(Counter), Counter()
    for it in ans:
        card = cards[key[it["id"]]["card_pack_id"]]["card"]
        sys_a = it.get("system") or "none"
        e = card.get("decisive_experiment") or {}
        card_vs["system same"] += _system(str(e.get("system"))) == sys_a
        card_vs["control: card states / Argon states"] += bool(features_of_card(card)["concurrent_control"]) and bool((it.get("design_features") or {}).get("concurrent_control"))
        card_vs["control: Argon states, card does not"] += (not features_of_card(card)["concurrent_control"]) and bool((it.get("design_features") or {}).get("concurrent_control"))
        fa, fc = features_of_argon(it), features_of_card(card)
        for x in it["alternatives"]:
            if x["kind"] != "methodological":
                continue
            t = x.get("threat") or "other"
            lists[sys_a][t] += 1
            rests[sys_a][x.get("design_feature") or "none"] += 1
            rows.append({"id": it["id"], "system": sys_a, "threat": t, "gold": x.get("design_on_expected_result"),
                         "from_argon_features": verdict(t, fa), "from_card": verdict(t, fc)})

    def agree(rs, k):
        pairs = [(r[k], r["gold"]) for r in rs if r["gold"] in ORDER]
        return {"n": len(pairs), "wkappa": wkappa(pairs), "exact": round(sum(a == b for a, b in pairs) / len(pairs), 3) if pairs else None}
    out = {
        "hypotheses": len(ans), "systems": dict(Counter(i.get("system") for i in ans)),
        "experiment": dict(Counter(i.get("experiment") for i in ans)),
        "features_stated": dict(Counter(k for i in ans for k, v in (i.get("design_features") or {}).items() if v)),
        "methodological": len(rows), "substantive": sum(1 for i in ans for x in i["alternatives"] if x["kind"] == "substantive"),
        "lists": {s: {"threats": dict(c), "other_share": round(c.get("other", 0) / sum(c.values()), 3),
                      "outside_the_list_of_its_system": sum(v for t, v in c.items() if s in LISTS and t not in LISTS[s] and t != "other")}
                  for s, c in lists.items()},
        "verdicts_rest_on": {s: {k: round(v / sum(c.values()), 2) for k, v in c.most_common()} for s, c in rests.items()},
        "card_against_argon": dict(card_vs),
        "gold_verdicts": dict(Counter(r["gold"] for r in rows)),
        "verdict_from_argon_features": agree(rows, "from_argon_features"),
        "verdict_from_card": agree(rows, "from_card"),
        "always_unchanged": agree([{**r, "u": "unchanged"} for r in rows], "u"),
        "by_system": {s: {"from_argon_features": agree([r for r in rows if r["system"] == s], "from_argon_features"),
                          "from_card": agree([r for r in rows if r["system"] == s], "from_card")} for s in sorted({r["system"] for r in rows})},
        "rows": rows,
    }
    (D / "pack_28_score.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return {k: v for k, v in out.items() if k != "rows"}


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

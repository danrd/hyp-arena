"""Argon pack 20: the 60 texts of pack 17 labelled again under the link-type definitions of docs/system/card.md (card_gold_v2,
the same instructions as pack 19 plus the rules for registry texts). Free, deterministic, no model call.

    python -m scripts.pack20_relabel build   # longevity-kg/reviews/argon-2026-11-13/pack_20{a,b}_task.json, pack_20_key.json

The texts are pack 17's, unchanged (registry texts with their design lines); new ids and a new order, so the answer cannot be
read off the earlier one. Uses: (1) the card gold under the new definitions for the registry texts; (2) how much the new
definitions change the outside reader's own labels on the same texts (pack 17 against pack 20).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from scripts.pack19_card import INSTRUCTIONS as V2

HA = Path(__file__).resolve().parents[1]
KG = HA.parent / "longevity-kg"
SRC = KG / "reviews" / "argon-2026-11-12"
OUT = KG / "reviews" / "argon-2026-11-13"

REGISTRY = """
Some texts are registry trials (they begin "A trial registered to test the following." and carry lines such as Title,
Conditions, Interventions, Summary, Design, Arms, Primary outcomes). For them:
- outcomes: the registry's primary outcomes are main (several primary outcomes are all main and equal); other outcomes the
  text expects are not main; the title's topic (e.g. "improving pre-sarcopenia") is the topic, not an outcome, unless it is
  itself a primary outcome;
- population.condition: the state of the people selected (from Conditions and the text, e.g. "pre-sarcopenia");
- interventions and background from Interventions and Arms (what every arm receives alike is background);
- experiment from Design, Arms and Planned enrollment; the comparator from the control arm;
- hypothesis_kind is usually interventional and main_factor the intervention;
- text_reads_as_result: true when the title or text reports the result (e.g. "X Increases Y").
The answer format is the same; set "task" to "card_gold_v2" and use the ids given here.
"""


def _h(*x) -> str:
    return hashlib.sha1("|".join(map(str, x)).encode()).hexdigest()


def build() -> dict:
    items = {i["id"]: i for p in "ab" for i in json.loads((SRC / f"pack_17{p}_task.json").read_text())["items"]}
    key17 = json.loads((SRC / "pack_17_key.json").read_text())
    order = sorted(items, key=lambda k: _h("order20", k))
    task, key = {"A": [], "B": []}, {}
    for i, k in enumerate(order, 1):
        pid = f"P{i:02d}"
        task["A" if i % 2 else "B"].append({"id": pid, "text": items[k]["text"]})
        key[pid] = {**key17[k], "pack17_id": k}
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for part, its in task.items():
        f = OUT / f"pack_20{part.lower()}_task.json"
        f.write_text(json.dumps({"task": "card_gold_v2", "part": part, "written_on": "2026-11-13", "instructions": V2 + REGISTRY,
                                 "items": its}, indent=1, ensure_ascii=False) + "\n")
        sizes[part] = {"texts": len(its), "kb": round(f.stat().st_size / 1024)}
    (OUT / "pack_20_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    return {"parts": sizes, "groups": {g: sum(v["group"] == g for v in key.values()) for g in {v["group"] for v in key.values()}}}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1, ensure_ascii=False))

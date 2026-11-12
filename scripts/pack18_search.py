"""Argon pack 18: the search gold (docs/benchmarks/README.md, stages 3 and 6). Free, deterministic, no model call.

    python -m scripts.pack18_search build    # longevity-kg/reviews/argon-2026-11-12/pack_18_task.json, pack_18_key.json

30 calibration trials (T in the past, our search logs saved in run_{s}_v10.json, so the recall of our search is computed
at once), none of them in packs 16 or 17. Argon gets the registry text and T only, not our chain (no anchoring), and lists
the papers published on or before T that a careful search must find: the closest prior work (novelty), direct evidence on
the outcome, evidence on each step the text states, and evidence against. Every third trial (hash order) is holdout.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HA = Path(__file__).resolve().parents[1]
KG = HA.parent / "longevity-kg"
OUT = KG / "reviews" / "argon-2026-11-12"
N = 30

INSTRUCTIONS = """You are building a gold standard for a literature search. Each item is a registered clinical trial (its registry
text) and a date T. List the papers published ON OR BEFORE T that a careful systematic search for this hypothesis MUST find.
Check every PMID and its publication date in PubMed; never give a paper published after T, even if you know it; never give
a PMID you have not checked.

Per trial:
1. closest_prior_work: the earlier study closest to this trial (the same intervention, or the nearest one, on the same outcome;
   in the same population if one exists), with its PMID, year and one line on how it differs (population, dose, design,
   species); and novelty_level: known_result (the same intervention, population and outcome already tested with a clear
   result) | new_context (same intervention and outcome, another population, age, sex or dose) | translation (only in another
   species) | analog (only a related intervention of the same kind) | new (nothing close).
2. papers: up to 15, the most important first. Each:
   {pmid, year, shows (one line: the result), category: prior_trial (an earlier trial of the same intervention and outcome) |
    direct (same intervention or same kind, the trial's outcome) | step (evidence on a step of the reasoning the text states;
    name the step in `step`) | against (a null or opposite result on the outcome or a step) | review (a systematic review or
    meta-analysis on the outcome),
    population: exact | adjacent | other_species, must_find: true for the up to 5 papers no evaluation may miss, step: null or
    the step in a few words}.
3. note: one sentence on how well the question was studied before T.

Answer with one JSON object, nothing else:
{"task": "search_gold_v1", "items": [{"id": "S01", "closest_prior_work": {"pmid": "", "year": 0, "differs": ""},
  "novelty_level": "", "papers": [{"pmid": "", "year": 0, "shows": "", "category": "", "population": "", "must_find": true,
  "step": null}], "note": ""}]}
"""


def _h(*x) -> str:
    return hashlib.sha1("|".join(map(str, x)).encode()).hexdigest()


def build() -> dict:
    rows = [json.loads(l) for l in (KG / "hypothesis_db" / "rows.jsonl").read_text().splitlines()]
    used = set()
    for k in ("pack_16_key.json", "pack_17_key.json"):
        for v in json.loads((OUT / k).read_text()).values():
            used.add(v.get("unit") and f"{v.get('unit')}" or v.get("row", "").split(":", 1)[-1])
    cal = [r for r in rows if "calibration-74" in r["sets"] and r.get("text") and r.get("T") and r["source_id"] not in used]
    picked = sorted(cal, key=lambda r: _h("pack18", r["id"]))[:N]
    for i, r in enumerate(sorted(picked, key=lambda r: _h("hold18", r["id"]))):
        r["holdout"] = i % 3 == 2
    task, key = [], {}
    for i, r in enumerate(picked, 1):
        sid = f"S{i:02d}"
        task.append({"id": sid, "T": r["T"], "text": r["text"]})
        key[sid] = {"row": r["id"], "short": r["short"], "unit": r["source_id"], "T": r["T"], "holdout": r["holdout"],
                    "outcome": r.get("outcome")}
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "pack_18_task.json"
    f.write_text(json.dumps({"task": "search_gold_v1", "written_on": "2026-11-12", "instructions": INSTRUCTIONS, "items": task},
                            indent=1, ensure_ascii=False) + "\n")
    (OUT / "pack_18_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    return {"trials": len(task), "kb": round(f.stat().st_size / 1024), "holdout": sum(v["holdout"] for v in key.values()),
            "T_range": [min(v["T"] for v in key.values()), max(v["T"] for v in key.values())]}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1, ensure_ascii=False))

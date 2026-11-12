"""Argon pack 17: the card gold (docs/benchmarks/README.md, stage 2; specs/mechanism-chain-comparison-2026-11-11.yaml texts).
Free, deterministic (hash order), no model call. Writes the task in two parts and the hidden key to the private repository.

    python -m scripts.pack17_card build    # longevity-kg/reviews/argon-2026-11-12/pack_17{a,b}_task.json, pack_17_key.json

60 texts: 20 registry trials whose text gives a reason (a code cue: because, via, by increasing, mediated, thereby ...),
20 without one (control: a chain should add nothing), 20 hypotheses written with a mechanism (Bio Arena 12, at most 3 per
author; the ChatGPT set 8). H86 and H49 (the walkthroughs) are in by name. Every third text of a group (hash order) is
holdout. Argon reads the text only (no literature), except the last question (weakest step), which names its PMIDs.
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

HA = Path(__file__).resolve().parents[1]
KG = HA.parent / "longevity-kg"
OUT = KG / "reviews" / "argon-2026-11-12"
FORCE = {"H86", "H49"}
CUE = re.compile(r"\b(because|via|through (the )?(activation|inhibition|reduction|increase|modulat\w*)|mechanism\w*|by (increasing|"
                 r"reducing|improving|inhibiting|activating|enhancing|restoring|lowering|stimulating)|mediated|leads? to|which "
                 r"(in turn|may|could|would)|thereby|resulting in)\b", re.I)

INSTRUCTIONS = """You are building a gold standard for how a research hypothesis is parsed into a card. Work ONLY from the text of
each item: do not add anything from your own knowledge (a step the text does not state does not exist), except in the last
question (weakest_step), where you may use the literature published before the date T.

For each text answer:

1. text_reads_as_result: true when the text reports the result instead of stating a hypothesis (a title like "X increases Y",
   past tense "the trial showed"), with result_phrase copied exactly; else false and null.
2. population: {species, condition, age, sex, phrase} - only what the text states (else null), phrase copied exactly.
3. interventions: a list; each {name, kind: compound | diet | exercise | procedure | device | behavioural | other, dose_or_regimen,
   route, phrase}. background: a list of what EVERY group receives alike (e.g. the same exercise programme in both arms), each
   with its phrase; something given to all groups is background, not an intervention.
4. comparator: {kind: placebo | sham | active | usual_care | no_intervention | none_stated, description, phrase}.
5. outcomes: every outcome the hypothesis claims, each {measure, direction: increase | decrease | improve | worsen | none_stated,
   primary: true/false (primary = the registry's primary outcome, else the first named), time_point, phrase}.
6. expected_effect: the size of the effect the text expects (e.g. "1 point on SPPB", "20% fewer falls", a sample-size
   assumption), with what it is compared to and the time point, and the phrase; null when the text names no size.
7. claims: every step of the reasoning the text STATES, in order from the intervention to the outcome, each:
   {id (s1, s2 ...), subject, relation (plain words), object, phrase (copied exactly, the shortest span that states it),
    stated_as: claimed (part of the hypothesis) | known (stated as an accepted fact) | analogy (the same in another species or
    for a related intervention, given as support),
    link: delivery (the intervention is given and reaches its site; adherence for a programme) | engagement (it acts on its
    target) | pathway (a molecular or cellular process changes) | effect (an intermediate state of a tissue or organ) |
    outcome (the clinical or functional result claimed) | population_state (a fact about the people or animals the hypothesis
    rests on, e.g. "levels of Y are low in this condition") | none (not a step of the chain),
    level: molecule | cell | tissue | organ | organism,
    after: the id of the step it follows from, or null}.
   The outcomes of item 5 appear here too as claims with link outcome. Write no step the text does not state; a text with no
   reason gives only outcome claims.
8. experiment: {design: randomised | non_randomised | single_arm | crossover | observational | not_stated, arms (number),
   arm_list (each: label and what it receives), masking (who is masked, or none / not_stated), n_planned (a number only if
   stated as planned), primary_outcomes (each with its time frame), duration, phrase} - only what the text states.
9. ai_role: {stated: none | analysis | in_the_loop | intervention, stated_phrase (exactly, or null)} - only a role the text
   states; and separately ai_role_plausible: the role AI could naturally play in testing this hypothesis (same scale), with
   a one-line reason - this second part is your judgement and is kept apart.
10. weakest_step: the id of the step on which the hypothesis rests most and that is least supported in the literature
    before T, with up to 3 PMIDs (published before T) behind your judgement; null for a text with outcome claims only.

Answer with one JSON object, nothing else:
{"task": "card_gold_v1", "part": "A | B", "items": [{"id": "K01", "text_reads_as_result": false, "result_phrase": null,
  "population": {...}, "interventions": [...], "background": [...], "comparator": {...}, "outcomes": [...],
  "expected_effect": null, "claims": [...], "experiment": {...}, "ai_role": {...}, "ai_role_plausible": {...},
  "weakest_step": {"id": null, "pmids": [], "why": ""}}]}
"""


def _h(*x) -> str:
    return hashlib.sha1("|".join(map(str, x)).encode()).hexdigest()


def build() -> dict:
    rows = [json.loads(l) for l in (KG / "hypothesis_db" / "rows.jsonl").read_text().splitlines()]
    reg = [r for r in rows if r["kind"] == "registry trial" and set(r["sets"]) & {"calibration-74", "prospective-60", "benchmark-v2"}
           and r.get("text")]
    for r in reg:
        r["cue"] = bool(CUE.search(r["text"]))
    picked = []

    def take(cands, n, group):
        chosen = [r for r in cands if r["short"] in FORCE]
        for r in sorted(cands, key=lambda r: _h("pack17", r["id"])):
            if len(chosen) >= n:
                break
            if r not in chosen:
                chosen.append(r)
        picked.extend(dict(r, group=group) for r in chosen[:n])

    take([r for r in reg if r["cue"]], 20, "registry_reason")
    take([r for r in reg if not r["cue"] and r["id"] not in {p["id"] for p in picked}], 20, "registry_no_reason")
    # written mechanisms: Bio Arena (at most 3 per author) and the ChatGPT set
    authors = {}
    for line in gzip.open(KG / "external" / "bioarena" / "2026-10-19" / "hypotheses.jsonl.gz", "rt"):
        h = json.loads(line)["hypothesis"]
        authors[f"bioarena:{h['id']}"] = h.get("author") or ""
    per = collections.Counter()
    ba = []
    for r in sorted([r for r in rows if r["source"] == "bioarena" and CUE.search(r["text"] or "")], key=lambda r: _h("pack17", r["id"])):
        a = authors.get(r["id"], "")
        if per[a] < 3 and len(ba) < 12:
            per[a] += 1
            ba.append(dict(r, group="written_mechanism"))
    ch = sorted([r for r in rows if r["source"] == "chatgpt"], key=lambda r: _h("pack17", r["id"]))[:8]
    picked += ba + [dict(r, group="written_mechanism") for r in ch]
    for g in {p["group"] for p in picked}:
        for i, p in enumerate(sorted([p for p in picked if p["group"] == g], key=lambda p: _h("hold17", p["id"]))):
            p["holdout"] = i % 3 == 2 and p["short"] not in FORCE
    picked.sort(key=lambda p: _h("order17", p["id"]))
    # the text as the current text builder writes it: registry design lines added where the saved text predates them
    from scripts.benchmark_run import _ctgov, _ctgov_design, _text
    cache: dict = {}
    for p in picked:
        if p["source"].startswith("ctgov") and "\nDesign:" not in p["text"]:
            extra = _text(_ctgov_design(_ctgov(p["source_id"], cache)))
            lines = p["text"].split("\n")
            i = next((k for k, l in enumerate(lines) if l.startswith("Primary outcomes")), len(lines))
            p["text"] = "\n".join(lines[:i] + ([extra] if extra else []) + lines[i:])
            p["design_lines_added"] = True
    task, key = {"A": [], "B": []}, {}
    for i, p in enumerate(picked, 1):
        kid = f"K{i:02d}"
        task["A" if i % 2 else "B"].append({"id": kid, "T": p.get("T") or p.get("written_on") or "", "text": p["text"]})
        key[kid] = {"row": p["id"], "short": p["short"], "group": p["group"], "holdout": p["holdout"], "source": p["source"],
                    "design_lines_added": p.get("design_lines_added", False)}
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for part, its in task.items():
        f = OUT / f"pack_17{part.lower()}_task.json"
        f.write_text(json.dumps({"task": "card_gold_v1", "part": part, "written_on": "2026-11-12", "instructions": INSTRUCTIONS,
                                 "items": its}, indent=1, ensure_ascii=False) + "\n")
        sizes[part] = {"texts": len(its), "kb": round(f.stat().st_size / 1024)}
    (OUT / "pack_17_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    return {"parts": sizes, "groups": dict(collections.Counter(v["group"] for v in key.values())),
            "holdout": sum(v["holdout"] for v in key.values()),
            "forced": [v["short"] for v in key.values() if v["short"] in FORCE],
            "sources": dict(collections.Counter(v["source"] for v in key.values()))}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1, ensure_ascii=False))

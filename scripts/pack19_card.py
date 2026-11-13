"""Argon pack 19: the card gold on texts that are not registry trials (docs/benchmarks/README.md, stage 2). Free,
deterministic (hash order), no model call. Writes the task and the hidden key to the private repository.

    python -m scripts.pack19_card build    # longevity-kg/reviews/argon-2026-11-13/pack_19_task.json, pack_19_key.json

30 texts, none of them in pack 17: Bio Arena 12 (at most 3 per author), the ChatGPT set 10, our evolved versions 8. Every third text of a group (hash order) is holdout. The instructions carry the
link-type definitions of docs/system/card.md ("Звенья: как определяется тип"): the outcome first, then the intervention's
chain, and premises about the problem kept off the chain; one relation and one measure per claim; labels in English.
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import sys
from pathlib import Path

HA = Path(__file__).resolve().parents[1]
KG = HA.parent / "longevity-kg"
OUT = KG / "reviews" / "argon-2026-11-13"
FORCE: set = set()

INSTRUCTIONS = """You are building a gold standard for how a research hypothesis is parsed into a card. The texts are NOT
registry trials: they are research hypotheses written by people or models, often about a mechanism, in Russian or English.
Work ONLY from the text of each item: add nothing from your own knowledge; a step the text does not state does not exist.
Write every label (subject, object, measure, name) in ENGLISH, whatever the language of the text; every "phrase" is copied
exactly from the text, character for character, in the text's own language (the shortest continuous span that states it).

Parse in this order.

1. hypothesis_kind: interventional (something is given or done and a result follows) | mechanistic (A causes B in ageing or
   disease; the hypothesis is about the cause) | explanatory (why something happens or could go wrong, e.g. a side effect of
   an intervention under some condition) | other. main_factor: {name, kind: intervention | exposure | condition | process,
   phrase} - the thing whose consequences the hypothesis states (for "rejuvenating the thymus may harm old tissues" it is the
   thymus rejuvenation, not a manipulation of the experiment).
2. topic: the disease or ageing process the hypothesis is about, in plain words (e.g. "sarcopenia", "immunosenescence"),
   with its phrase.
3. text_reads_as_result: true when the text reports a result instead of stating a hypothesis, with result_phrase; else false.
4. population: {species, condition (the state of the people or animals the hypothesis is about or that are selected, e.g.
   "pre-sarcopenia", "aged mice"), age_as_stated (exactly as the text gives it, e.g. "20 months", "older adults"), sex,
   strain (animals only), phrase} - only what the text states, else null.
5. outcomes (FIRST decide what the hypothesis claims as its result): each {measure (ONE measure per outcome), direction:
   increase | decrease | improve | worsen | none_stated, main: true for the result the hypothesis puts first (the prediction
   or the claimed effect), time_point, phrase}. An outcome is defined by its role in the text (what is promised to change),
   not by its level: a tissue measure promised as the result is an outcome.
6. interventions: what is given or done to cause the result, each {name, kind: compound | diet | exercise | procedure |
   gene | cell | device | behavioural | exposure | other, dose_or_regimen, route, phrase}; background: what every group
   receives alike. A manipulation that only TESTS the hypothesis (a knockout, an added antigen, an inhibitor used to block a
   step) is not the intervention: put it in experiment.arm_list.
7. claims: one relation and one measure per claim, each {id (s1 ...), subject, relation (plain words), object, phrase,
   stated_as: claimed | known | analogy, part: chain | premise, link, premise_kind, level: molecule | cell | tissue | organ |
   organism, after: the id of the step it follows from or null}.
   part = chain when the subject is the intervention (or its component) or a step caused by it earlier in the chain; then
   link is one of:
     delivery - the intervention is carried out and reaches its site (exposure, blood level, adherence);
     engagement - it acts directly on a NAMED target molecule (no named molecule, no engagement);
     pathway - a process inside cells changes (signalling, gene expression, protein synthesis, autophagy, cellular
       mitochondrial function);
     effect - a state of a tissue, organ or body system changes on the way to the outcome and is not itself promised as the
       result (muscle mass, strength, stiffness, bone density, number of cells of a type in a tissue, systemic inflammation,
       a hormone level);
     outcome - one of the outcomes of item 5 (a step that is the same measure as an outcome is that outcome; a known
       statement about it is an outcome stated as known).
   part = premise when the subject is NOT the intervention: age, the disease, the condition or behaviour of the people
   ("pre-sarcopenia affects 10-20% of older adults", "loneliness is a risk factor for cognitive decline", "thymus ageing
   alters T-cell selection"). A premise has link null and premise_kind: population_state (a fact about the people: how
   common, what level of a measure) | problem_mechanism (how age or disease leads to harm).
   The type of a step is set by WHAT CHANGES; known or claimed does not change the link. A step said of a class the
   intervention belongs to ("resistance exercise may increase muscle mass" for squats) keeps the text's subject.
8. experiment: {design: randomised | non_randomised | single_arm | crossover | observational | in_vitro | animal |
   not_stated, system: human | mouse | rat | cells | other | not_stated, arm_list (each: label and what it receives,
   including test manipulations), comparator: {kind: placebo | sham | active | usual_care | no_intervention | control_agent |
   none_stated, description, phrase}, primary_measures (what is measured), duration, n_planned, phrase} - only what the text
   states.
9. expected_effect: a size the text expects, with comparison and time point, and phrase; else null.
10. declared: {alternatives, decision_or_falsification_criteria, risks} - each as stated (phrase) or null.

Answer with one JSON object, nothing else:
{"task": "card_gold_v2", "items": [{"id": "N01", "hypothesis_kind": "", "main_factor": {...}, "topic": {...},
  "text_reads_as_result": false, "result_phrase": null, "population": {...}, "outcomes": [...], "interventions": [...],
  "background": [...], "claims": [...], "experiment": {...}, "expected_effect": null, "declared": {...}}]}
"""


def _h(*x) -> str:
    return hashlib.sha1("|".join(map(str, x)).encode()).hexdigest()


def build() -> dict:
    rows = [json.loads(l) for l in (KG / "hypothesis_db" / "rows.jsonl").read_text().splitlines()]
    used = {v["row"] for v in json.loads((KG / "reviews" / "argon-2026-11-12" / "pack_17_key.json").read_text()).values()}
    authors = {}
    for line in gzip.open(KG / "external" / "bioarena" / "2026-10-19" / "hypotheses.jsonl.gz", "rt"):
        h = json.loads(line)["hypothesis"]
        authors[f"bioarena:{h['id']}"] = h.get("author") or ""
    per, ba = collections.Counter(), []
    for r in sorted([r for r in rows if r["source"] == "bioarena" and r.get("text") and r["id"] not in used],
                    key=lambda r: _h("pack19", r["id"])):
        a = authors.get(r["id"], "")
        if per[a] < 3 and len(ba) < 12:
            per[a] += 1
            ba.append(dict(r, group="bioarena"))
    ch = [r for r in rows if r["source"] == "chatgpt" and r["id"] not in used]
    ch = [r for r in ch if r["id"] in FORCE] + sorted([r for r in ch if r["id"] not in FORCE], key=lambda r: _h("pack19", r["id"]))
    ev = sorted([r for r in rows if r["source"] == "ours/evolution" and r.get("text") and r["id"] not in used],
                key=lambda r: _h("pack19", r["id"]))
    picked = ba + [dict(r, group="chatgpt") for r in ch[:10]] + [dict(r, group="evolved") for r in ev[:8]]
    for g in {p["group"] for p in picked}:
        for i, p in enumerate(sorted([p for p in picked if p["group"] == g], key=lambda p: _h("hold19", p["id"]))):
            p["holdout"] = i % 3 == 2 and p["id"] not in FORCE
    picked.sort(key=lambda p: _h("order19", p["id"]))
    task, key = [], {}
    for i, p in enumerate(picked, 1):
        nid = f"N{i:02d}"
        task.append({"id": nid, "text": p["text"]})
        key[nid] = {"row": p["id"], "short": p.get("short"), "group": p["group"], "holdout": p["holdout"], "source": p["source"]}
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "pack_19_task.json"
    f.write_text(json.dumps({"task": "card_gold_v2", "written_on": "2026-11-13", "instructions": INSTRUCTIONS, "items": task},
                            indent=1, ensure_ascii=False) + "\n")
    (OUT / "pack_19_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    return {"texts": len(task), "kb": round(f.stat().st_size / 1024), "groups": dict(collections.Counter(v["group"] for v in key.values())),
            "holdout": sum(v["holdout"] for v in key.values()), "forced": [v["row"] for v in key.values() if v["row"] in FORCE],
            "authors_bioarena": len({authors.get(p["id"]) for p in ba})}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1, ensure_ascii=False))

"""Argon pack 28: the alternatives gold on hypotheses that are not registry trials (specs/alternatives/design-rule-2026-11-16.yaml,
universal_rule): the 30 hypotheses of pack 26 (Bio Arena, chat-written, evolved versions; humans, mice, cells), the main
alternative explanations of the result the stated experiment would show, the kind of each, and what the experiment as the
text states it does to each. Free, deterministic, no model call.

    python -m scripts.argon.pack28_alternatives build   # longevity-kg/reviews/argon-2026-11-16/pack_28_task.json, pack_28_key.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KG = Path(__file__).resolve().parents[2].parent / "longevity-kg"
SRC = KG / "reviews" / "argon-2026-11-15"
OUT = KG / "reviews" / "argon-2026-11-16"

INSTRUCTIONS = """You are building a gold standard for one step of a hypothesis-evaluation system: competing explanations.
Each item is a research hypothesis as its author wrote it (some are in Russian) and a date T. The text may or may not state
an experiment; the experiment may be in humans, in animals, in cells or an analysis of existing data. Suppose the experiment
the text states is run and gives the result the hypothesis predicts. List the main ALTERNATIVE explanations of that result:
ways the result could arise other than the way the hypothesis says. Use only what was knowable on or before T. Judge the
experiment exactly as the text states it: do not improve it and do not assume a control, a randomisation or a blinding the
text does not mention.

Per hypothesis:
0. experiment: stated | partly (a system or a readout is named, no design) | none; system: human | animal | cells |
   data_analysis | mixed | none; and the design features THE TEXT STATES, each with the exact phrase or null:
   concurrent_control (what the comparison group gets), allocation (randomised or how groups are formed), blinding (who),
   replication (independent animals, litters, cell lines or cohorts), specificity_control (a second tool, a rescue, a
   dose-response, an inactive analogue), readout (the measure and when).
1. alternatives: up to 5, the most important first (rank 1 = the one a careful reviewer would raise first). Two kinds:
   - substantive: another cause or mechanism in the world (another component of the intervention does the work; an
     off-target or general route - stress, toxicity, reduced food intake, weight loss, altered development; the system
     changes on its own; a co-intervention). Write it as a claim: subject - relation - object.
   - methodological: an artefact of how the experiment is run or measured. Name its threat from this list, or "other":
     humans: practice (learning on a repeated test) | regression (regression to the mean, natural course) | assessor
       (the rater knows the arm) | expectation (placebo response, unblinded participants) | attention (unequal contact) |
       selection (selection, attrition, baseline differences) | cointervention (adherence, other treatments) | multiplicity;
     animals: allocation (cage, litter or batch effects, non-random groups) | assessor | attrition (exclusions, survival
       of the fittest animals) | handling (stress, vehicle, route) | housing (diet, microbiome, site) | sex_strain_age (one
       sex, strain or age only) | multiplicity;
     cells: batch (passage, clone, donor, batch of reagent) | off_target (of an siRNA, a CRISPR guide, an inhibitor) |
       vehicle (solvent, transfection, viral load) | culture_artefact (non-physiological dose, oxygen, medium, 2D culture) |
       line_identity | multiplicity;
     data analysis: confounding | reverse_causation | selection | measurement | multiplicity.
   For each alternative give:
   - statement: one sentence; subject, relation, object (short labels, in English);
   - kind: substantive | methodological; threat: one of the names above, "other" or null for a substantive one;
   - distinguishing_part: what the alternative says that the hypothesis does not;
   - design_on_expected_result: what the experiment AS STATED does to this alternative if the predicted result comes out:
     eliminated (the stated design rules it out) | weakened | unchanged (the stated design cannot tell them apart; also
     when the text states no experiment);
   - design_feature: which of the features of point 0 your verdict rests on (concurrent_control | allocation | blinding |
     replication | specificity_control | readout | none), and design_phrase: the exact phrase of the text ("" if none);
   - design_on_null_result: the same if the experiment finds no effect;
   - would_eliminate: the one addition to the experiment that would rule this alternative out, in a few words.
2. literature, for each SUBSTANTIVE alternative of rank 1-2: up to 3 papers published ON OR BEFORE T that weigh its
   distinguishing part: {pmid, title, first_author, year, shows, stance: for | against}. Open the PubMed record of every
   PMID you give; a PMID whose record does not match, or that is published after T, is rejected. Fewer is better than
   unchecked.

Answer with one JSON object, nothing else:
{"task": "alternatives_gold_v2", "items": [
  {"id": "B01", "experiment": "stated", "system": "animal",
   "design_features": {"concurrent_control": null, "allocation": null, "blinding": null, "replication": null,
                       "specificity_control": null, "readout": null},
   "alternatives": [
     {"rank": 1, "kind": "methodological", "threat": "allocation", "statement": "...", "subject": "...", "relation": "...",
      "object": "...", "distinguishing_part": "...", "design_on_expected_result": "unchanged", "design_feature": "none",
      "design_phrase": "", "design_on_null_result": "unchanged", "would_eliminate": "...", "literature": []}],
   "note": ""}
]}
"""


def build() -> dict:
    task = json.loads((SRC / "pack_26_task.json").read_text())["hypotheses"]
    key26 = json.loads((SRC / "pack_26_key.json").read_text())
    items, key = [], {}
    for n, h in enumerate(task, 1):
        bid = f"B{n:02d}"
        items.append({"id": bid, "T": h["T"], "text": h["text"]})
        key[bid] = {"pack_26_id": h["id"], **{k: key26[h["id"]][k] for k in ("card_pack_id", "row", "source")}}
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "pack_28_task.json"
    f.write_text(json.dumps({"task": "alternatives_gold_v2", "written_on": "2026-11-16", "instructions": INSTRUCTIONS,
                             "items": items}, indent=1, ensure_ascii=False) + "\n")
    (OUT / "pack_28_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    return {"items": len(items), "kb": round(f.stat().st_size / 1024)}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

"""Argon pack 6: a second reader of I (specs/informativeness-check-2026-11-08.yaml). Free (no model calls).

    python -m scripts.pack6_informativeness build     # -> longevity-kg reviews/argon-2026-11-08/pack_6_task.json + pack_6_key.json
"""
from __future__ import annotations

import json
import sys

from hyparena.card import rules_v32 as r32
from hyparena.card.models import Claim
from scripts.v34_check import CAL, PROS, parts

DIR = CAL.parents[1] / "reviews" / "argon-2026-11-08"
INSTRUCTIONS = """You are reviewing how informative a planned experiment is, the way a methodologist would.

Each item is a registered clinical trial (the registry text as given) and the ALTERNATIVE EXPLANATIONS a model proposed:
other reasons why the trial could show the result it expects, without the mechanism the trial assumes. For each alternative
you see what it claims, the model's rationale and the PMIDs the model cited for it.

Part 1, per alternative:
- d_positive: if the trial's result is POSITIVE, what does it do to this alternative? eliminated | weakened | unchanged.
  "eliminated" only when the trial has a named arm, control or measurement for which the hypothesis and the alternative
  predict different results (e.g. an attention-matched active control rules out "any attention helps"); "weakened" when the
  trial only measures something the alternative depends on, without an arm that separates them; "unchanged" otherwise.
  A design label alone ("randomised", "double-blind") is not enough unless it is the feature that separates the two.
- d_negative: the same for a NULL result.
- separating_feature: the verbatim registry phrase (arm, control or measurement) that separates them, or null.
- genuine: yes | partly | no. Would the alternative, if true, produce the result the trial expects without the trial's own
  mechanism? "no" for alternatives that are irrelevant, restate the hypothesis, or could not produce that result.
- support: none | weak | moderate | strong: how well the literature you know supports the alternative itself; up to 3 PMIDs.

Part 2, per trial:
- missing_alternatives: up to 3 important alternative explanations the list does not contain (subject, relation, object in
  plain words), each with d_positive, d_negative and support as above. Empty if the list is complete.
- informativeness: 0 to 1, how much the result of this trial, whatever it is, would change a careful reviewer's belief that
  the stated mechanism is real (0 nothing, 1 decisive).
- best_change: one sentence, the single change of design that would raise informativeness most.

Answer with one JSON object, nothing else:
{"task": "informativeness", "trials": [{"id": "NCT...", "alternatives": [{"id": "p1", "d_positive": "...", "d_negative": "...",
  "separating_feature": "..." | null, "genuine": "...", "support": "...", "pmids": ["..."]}],
  "missing_alternatives": [{"text": "...", "d_positive": "...", "d_negative": "...", "support": "...", "pmids": []}],
  "informativeness": 0.4, "best_change": "..."}]}
"""


def build() -> dict:
    run = json.loads((PROS / "run_60.json").read_text())
    texts = {json.loads(l)["id"]: json.loads(l)["text"] for l in (PROS / "texts_60.jsonl").read_text().splitlines() if l.strip()}
    trials, key = [], {}
    for h, r in sorted(run.items()):
        it = r["items"][0]
        if not (it.get("card") and it.get("verification") and "v3" in it):
            continue
        card, cvs, alts = parts(it)
        e = r32.evaluate(card, cvs, alts, v36=True)
        rows, krows = [], {}
        for a in card.proposed_alternatives:
            rows.append({"id": a.id, "claim": f"{a.subject.label} - {a.relation.replace('_', ' ')} - {a.object.label}",
                         "qualifiers": a.qualifiers, "rationale": a.rationale, "cited_pmids": a.support_pmids})
            cv = alts.get(a.id)
            ac = Claim(id=a.id, subject=a.subject, relation=a.relation, object=a.object, qualifiers=a.qualifiers,
                       role="premise", source_span="")
            krows[a.id] = {"on_positive": a.on_positive, "on_negative": a.on_negative,
                           "a_v36": round(r32.current_support(cv.evidence if cv else [], cv.counterevidence if cv else [], ac), 4),
                           "records_for": len(cv.evidence) if cv else 0, "records_against": len(cv.counterevidence) if cv else 0}
        trials.append({"id": h, "registry_text": texts.get(h, ""), "alternatives": rows})
        key[h] = {"I_v36": e.I, "headroom_I": e.headroom_I, "alternatives": krows}
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "pack_6_task.json").write_text(json.dumps({"task": "informativeness", "instructions": INSTRUCTIONS,
                                                      "trials": trials}, indent=1, ensure_ascii=False) + "\n")
    (DIR / "pack_6_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    return {"trials": len(trials), "alternatives": sum(len(t["alternatives"]) for t in trials),
            "without_text": sum(1 for t in trials if not t["registry_text"]),
            "size_kb": round((DIR / "pack_6_task.json").stat().st_size / 1024)}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

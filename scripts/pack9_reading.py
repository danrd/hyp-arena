"""Argon pack 9: a gold of findings per (link, paper) for the reader's recall (specs/reading-gold-2026-11-08.yaml). Free.

    python -m scripts.pack9_reading build
"""
from __future__ import annotations

import hashlib
import json
import sys

from hyparena.card import rules_v3 as r3
from hyparena.tools import pubmed
from scripts.pilot_crosslink import sample as pilot_trials
from scripts.reread_v11 import items
from scripts.v34_check import CAL

DIR = CAL.parents[1] / "reviews" / "argon-2026-11-08"
INSTRUCTIONS = """You are building a gold standard for an evidence reader.

Each item is one CLAIM of a research hypothesis (subject - relation - object, with its qualifiers) and the abstracts a
search returned for it. For EVERY abstract decide whether the study itself reports a finding on the claim's relation:
- finding: for (the study's own result supports the relation), against (its own result is no effect or the opposite), or
  none (no own result on this relation: background, a review sentence without a result, another outcome, another
  intervention altogether, a protocol). A result in another population, species or dose, or for a related intervention of
  the same kind, still counts as for / against: say so in intervention_match and population_note.
- quote: the shortest sentence of the abstract, copied exactly, that gives the finding (null for none);
- design: rct | non_randomised | observational | animal | cells | review | meta_analysis | other;
- intervention_match: exact | class | other (as the claim names the intervention: a claim that names a kind is matched
  exactly by any study of that kind);
- population_note: "" or a few words on how the population differs from the claim's.
Use only what each abstract says. Judge every abstract; do not skip any.

Answer with one JSON object, nothing else:
{"task": "reading_gold", "items": [{"id": "L01", "papers": [{"pmid": "...", "finding": "for | against | none",
  "quote": "..." | null, "design": "...", "intervention_match": "...", "population_note": ""}]}]}
"""


def build() -> dict:
    want = set(pilot_trials())
    cand = []
    for h, as_of, card, cvs, logs in items("prospective"):
        if h not in want:
            continue
        for cl in r3.chain(card):
            ps = logs.get(cl.id, [])
            if len(ps) >= 10:
                cand.append((hashlib.sha1(f"gold|{h}|{cl.id}".encode()).hexdigest(), h, as_of, cl, ps))
    cand.sort(key=lambda x: x[0])
    picked = cand[:10]
    meta = pubmed.fetch(sorted({p for *_, ps in picked for p in ps}))
    task, key = [], {}
    for i, (_, h, as_of, cl, ps) in enumerate(picked, 1):
        iid = f"L{i:02d}"
        task.append({"id": iid, "T": as_of, "claim": f"{cl.subject.label} - {cl.relation.replace('_', ' ')} - {cl.object.label}",
                     "qualifiers": cl.qualifiers,
                     "papers": [{"pmid": p, "title": meta.get(p, {}).get("title", ""), "abstract": meta.get(p, {}).get("abstract", "")}
                                for p in ps if meta.get(p, {}).get("abstract")]})
        key[iid] = {"unit": h, "claim": cl.id}
    (DIR / "pack_9_task.json").write_text(json.dumps({"task": "reading_gold", "instructions": INSTRUCTIONS, "items": task},
                                                     indent=1, ensure_ascii=False) + "\n")
    (DIR / "pack_9_key.json").write_text(json.dumps(key, indent=1) + "\n")
    return {"links": len(task), "pairs": sum(len(t["papers"]) for t in task), "size_kb": round((DIR / "pack_9_task.json").stat().st_size / 1024)}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

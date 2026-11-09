"""Argon pack 10: abstract vs PMC full text vs knowledge graph (specs/sources-argon-2026-11-09.yaml). Free (PubMed / PMC metadata).

    python -m scripts.pack10_sources build
"""
from __future__ import annotations

import hashlib
import json
import sys

from hyparena.card import rules_v3 as r3
from hyparena.tools import pmc, pubmed
from scripts.pilot_crosslink import sample as pilot_trials
from scripts.reread_v11 import items
from scripts.v34_check import CAL

DIR = CAL.parents[1] / "reviews" / "argon-2026-11-08"
INSTRUCTIONS = """You test what each kind of source says about one link of a hypothesis, the way a systematic reviewer would.

Each item is a CLAIM (one link of a hypothesis's chain: subject - relation - object, with qualifiers), the date T, and up to
5 papers with PMID, PMCID, title and abstract. Every PMCID given is open access in PubMed Central. Use only papers published
on or before T for the verdicts.

For each paper:
A. From the ABSTRACT given here only: finding (for / against / none: the study's own result on the claim's relation),
   quote (verbatim from the abstract), design, n (participants or animals analysed), comparison (between_groups /
   within_group / pooled / none), effect (the phrase giving the size: a ratio, a standardised or mean difference with its
   interval), population (a few words).
B. From the open-access FULL TEXT in PMC (methods and results; use the PMCID; no other source): the same fields, the quote
   from the full text, and what changed versus A: a list from none, stance, effect, n, population, design, adds_finding
   (the full text has a result on the claim that the abstract lacks). If the full text cannot be opened in PMC, write
   "unavailable" and leave B empty.

For each claim:
C. From the literature you know up to T (your knowledge graph, not only the papers given): verdict (supported / mixed /
   refuted / no_evidence), strength (weak / moderate / strong / none), up to 5 key PMIDs with an effect size each where
   known. Also give the verdict you would reach from the given papers' abstracts alone (A) and from their full texts (B).

Answer with one JSON object, nothing else:
{"task": "sources", "items": [{"id": "S01",
  "papers": [{"pmid": "", "A": {"finding": "", "quote": "", "design": "", "n": null, "comparison": "", "effect": "", "population": ""},
              "B": {"status": "read | unavailable", "finding": "", "quote": "", "design": "", "n": null, "comparison": "", "effect": "",
                    "population": "", "changed": ["none"]}}],
  "verdict_A": {"verdict": "", "strength": ""}, "verdict_B": {"verdict": "", "strength": ""},
  "verdict_C": {"verdict": "", "strength": "", "key": [{"pmid": "", "effect": ""}]}}]}
"""


def build() -> dict:
    ans = {t["id"]: t for t in json.loads((DIR / "pack_8_answer.json").read_text())["trials"]}
    want = set(pilot_trials())
    cand = []
    for h, as_of, card, cvs, logs in items("prospective"):
        if h not in want or h not in ans:
            continue
        claims = {c.id: c for c in r3.chain(card)}
        for l in ans[h]["links"]:
            cl = claims.get(l["id"])
            if cl is None:
                continue
            kp = list(dict.fromkeys(l.get("pmids_for", []) + l.get("pmids_against", [])))
            cand.append((hashlib.sha1(f"sources10|{h}|{cl.id}".encode()).hexdigest(), h, as_of, cl, kp))
    cand.sort(key=lambda x: x[0])
    task, key = [], {}
    for _, h, as_of, cl, kp in cand:
        if len(task) >= 12:
            break
        open_ = []
        for p in kp:
            pc = pmc.pmcid(p)
            if pc and pmc.is_open(pc):
                open_.append((p, pc))
            if len(open_) >= 5:
                break
        if len(open_) < 2:
            continue
        meta = pubmed.fetch([p for p, _ in open_])
        iid = f"S{len(task) + 1:02d}"
        task.append({"id": iid, "T": as_of, "claim": f"{cl.subject.label} - {cl.relation.replace('_', ' ')} - {cl.object.label}",
                     "qualifiers": cl.qualifiers,
                     "papers": [{"pmid": p, "pmcid": pc, "title": meta.get(p, {}).get("title", ""), "abstract": meta.get(p, {}).get("abstract", "")}
                                for p, pc in open_]})
        key[iid] = {"unit": h, "claim": cl.id}
    (DIR / "pack_10_task.json").write_text(json.dumps({"task": "sources", "instructions": INSTRUCTIONS, "items": task},
                                                      indent=1, ensure_ascii=False) + "\n")
    (DIR / "pack_10_key.json").write_text(json.dumps(key, indent=1) + "\n")
    return {"links": len(task), "papers": sum(len(t["papers"]) for t in task), "candidates_seen": len(cand),
            "size_kb": round((DIR / "pack_10_task.json").stat().st_size / 1024)}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

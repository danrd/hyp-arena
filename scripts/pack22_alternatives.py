"""Argon pack 22: the gold for stage 7 (competing explanations): for the 30 calibration trials of the search gold (pack 18),
the main alternative explanations of the result the trial would show, what the stated design does to each, and the
literature on each before T. Free, deterministic, no model call.

    python -m scripts.pack22_alternatives build   # longevity-kg/reviews/argon-2026-11-14/pack_22_task.json, pack_22_key.json
    python -m scripts.pack22_alternatives check   # after the answer: every PMID against PubMed (title, first author, date <= T)

The texts and dates T are pack 18's (registry text as the text builder writes it); new ids, new order, and nothing of our
own alternatives is shown. Measures and the rule: specs/benchmark-alternatives-2026-11-14.yaml (written before the answer).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from scripts import bench_search as bs

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
OUT = KG / "reviews" / "argon-2026-11-14"

INSTRUCTIONS = """You are building a gold standard for one step of a hypothesis-evaluation system: competing explanations.
Each item is a registered clinical trial (its registry text) and a date T. Suppose the trial ends with the result its
authors expect on the primary outcome. List the main ALTERNATIVE explanations of that result: ways the result could arise
other than the way the hypothesis says. Use only what was knowable on or before T.

Per trial:
1. alternatives: up to 5, the most important first (rank 1 = the one a careful reviewer would raise first). Two kinds:
   - substantive: another cause or mechanism in the world (another component of the intervention does the work; the effect
     goes through a general route such as more physical activity, weight loss or social contact rather than the stated one;
     the population changes on its own; a co-intervention). Write it as a claim: subject - relation - object, as specific
     as the text allows.
   - methodological: an artefact of how the trial is run or measured (regression to the mean, expectation or placebo
     effect when not blinded, learning effect of a repeated test, differential dropout, unblinded assessor, measurement
     error, multiple outcomes).
   For each alternative give:
   - statement: one sentence; subject, relation, object (short labels, in English);
   - kind: substantive | methodological;
   - distinguishing_part: what the alternative says that the hypothesis does not (the part a study would have to show to
     support the alternative rather than the hypothesis);
   - design_on_expected_result: what the trial as registered (its Design, Arms, masking, comparator, outcomes) does to this
     alternative if the expected result comes out: eliminated (the design rules it out) | weakened (makes it less likely
     but does not rule it out) | unchanged (the design cannot tell them apart);
   - design_phrase: the exact phrase of the registry text that your verdict rests on ("" if the text says nothing and the
     verdict is unchanged);
   - design_on_null_result: the same if the trial finds no effect.
2. literature, for each SUBSTANTIVE alternative of rank 1-3: up to 5 papers published ON OR BEFORE T that a careful search
   must find to weigh this alternative: evidence for or against its distinguishing part. Each paper:
   {pmid, title, first_author, year, shows (one line: the result), stance: for | against (the alternative),
    shows_distinguishing_part: true | false}.
   Open the PubMed record of every PMID you give and copy its title and the first author's surname from it: a code check
   compares them with PubMed, and a PMID whose record does not match, or that is published after T, is rejected. Never give
   a PMID you have not opened. Fewer papers are better than unchecked ones; an alternative with no such literature gets [].

Answer format (JSON):
{"task": "alternatives_gold_v1", "items": [
  {"id": "A01", "alternatives": [
     {"rank": 1, "kind": "substantive", "statement": "...", "subject": "...", "relation": "...", "object": "...",
      "distinguishing_part": "...", "design_on_expected_result": "weakened", "design_phrase": "...",
      "design_on_null_result": "unchanged",
      "literature": [{"pmid": "", "title": "", "first_author": "", "year": 2010, "shows": "", "stance": "for",
                      "shows_distinguishing_part": true}]},
     {"rank": 2, "kind": "methodological", "statement": "...", "subject": "...", "relation": "...", "object": "...",
      "distinguishing_part": "...", "design_on_expected_result": "eliminated", "design_phrase": "...",
      "design_on_null_result": "unchanged", "literature": []}],
   "note": ""}
]}
Methodological alternatives need no literature. Do not add alternatives the trial's own design already names as its
comparison (the control arm itself is not an alternative).
"""


def _h(*x) -> str:
    return hashlib.sha1("|".join(map(str, x)).encode()).hexdigest()


def build() -> dict:
    task18 = {i["id"]: i for i in json.loads((bs.DIR / "pack_18_task.json").read_text())["items"]}
    key18 = json.loads((bs.DIR / "pack_18_key.json").read_text())
    order = sorted(task18, key=lambda s: _h("pack22", s))
    items, key = [], {}
    for n, sid in enumerate(order, 1):
        aid = f"A{n:02d}"
        items.append({"id": aid, "T": task18[sid]["T"], "text": task18[sid]["text"]})
        key[aid] = {"sid": sid, "unit": key18[sid]["unit"], "short": key18[sid].get("short"), "T": task18[sid]["T"],
                    "holdout": key18[sid]["holdout"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pack_22_task.json").write_text(json.dumps({"task": "alternatives_gold_v1", "written_on": "2026-11-14",
                                                      "instructions": INSTRUCTIONS, "items": items}, indent=1, ensure_ascii=False) + "\n")
    (OUT / "pack_22_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    return {"items": len(items), "holdout": sum(k["holdout"] for k in key.values())}


def check() -> dict:
    """Every PMID of the answer against PubMed: exists, title and first author match, date on or before T."""
    from scripts.pack21_pmid_fix import _same
    key = json.loads((OUT / "pack_22_key.json").read_text())
    ans = {i["id"]: i for i in json.loads((OUT / "pack_22_answer.json").read_text())["items"]}
    pm: dict = {}
    papers = [(aid, a.get("rank"), p) for aid, it in ans.items() for a in it.get("alternatives") or [] for p in a.get("literature") or []]
    bs.summaries(sorted({str(p.get("pmid")) for _, _, p in papers if p.get("pmid")}), pm)
    out, n = [], {"papers": len(papers), "valid": 0, "not_in_pubmed": 0, "title_or_author": 0, "after_T": 0}
    for aid, rank, p in papers:
        info = pm.get(str(p.get("pmid")), {})
        why = []
        if not info.get("exists"):
            why.append("not_in_pubmed")
        else:
            if not _same(p.get("title", ""), info.get("title", "")) or \
                    (p.get("first_author") or "").lower()[:5] not in (info.get("first_author") or "").lower():
                why.append("title_or_author")
            if info.get("earliest") and info["earliest"] > key[aid]["T"]:
                why.append("after_T")
        for w in why:
            n[w] += 1
        n["valid"] += not why
        out.append({"id": aid, "rank": rank, "pmid": str(p.get("pmid")), "valid": not why, "why": why,
                    "earliest": info.get("earliest"), "pubmed_title": info.get("title")})
    (OUT / "pack_22_check.json").write_text(json.dumps({"summary": n, "papers": out}, indent=1, ensure_ascii=False) + "\n")
    return n


if __name__ == "__main__":
    print(json.dumps({"build": build, "check": check}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

"""Argon pack 8: a second reader of the evidence balance, link by link (specs/balance-check-2026-11-08.yaml). Free.

    python -m scripts.pack8_balance build     # -> longevity-kg reviews/argon-2026-11-08/pack_8_task.json + pack_8_key.json
"""
from __future__ import annotations

import json
import sys

from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from scripts.v34_check import CAL, PROS, parts

DIR = CAL.parents[1] / "reviews" / "argon-2026-11-08"
INSTRUCTIONS = """You are checking, link by link, how well the published literature supported a research hypothesis at a given date,
the way a systematic reviewer would.

Each item is a registered clinical trial (registry text), the date T, and the hypothesis CHAIN a model extracted from it:
links from the intervention to the outcome (delivery, engagement of a target, pathway, intermediate effect, outcome), each
as subject - relation - object with qualifiers (species, population, measure, comparator...). Use only papers published ON
OR BEFORE T. Do not use anything later, even if you know it. Judge each link as stated, in its qualifiers (a result in mice
is weaker support for a claim about humans; a result for another compound of the same class is weaker than for the named
one).

Part 1, per link:
- verdict: supported (the evidence mostly supports the link) | mixed (real evidence on both sides) | refuted (the evidence
  mostly contradicts it, including well-powered null results) | no_evidence (nothing relevant published before T);
- strength: weak | moderate | strong (how firm the verdict is; GRADE-like: design, size, consistency, directness);
  "none" for no_evidence;
- pmids_for, pmids_against: up to 3 each, the most informative papers published on or before T.

Part 2, per trial: balance from -1 (the chain is refuted) through 0 (nothing known, or for and against balanced) to +1
(the chain is well supported), and one sentence why.

Answer with one JSON object, nothing else:
{"task": "balance", "trials": [{"id": "NCT...", "links": [{"id": "c1", "verdict": "...", "strength": "...",
  "pmids_for": ["..."], "pmids_against": ["..."]}], "balance": 0.4, "note": "one sentence"}]}
"""


def build() -> dict:
    run = json.loads((PROS / "run_60.json").read_text())
    texts = {json.loads(l)["id"]: json.loads(l)["text"] for l in (PROS / "texts_60.jsonl").read_text().splitlines() if l.strip()}
    trials, key = [], {}
    for h, r in sorted(run.items()):
        it = r["items"][0]
        if not (it.get("card") and it.get("verification") and "v3" in it):
            continue
        card, cvs, alts = parts(it, h)
        e = r32.evaluate(card, cvs, alts, v36=True)
        _, out = nv.slots(card)
        chain = [{"id": c.id, "type": c.link, "claim": f"{c.subject.label} - {c.relation.replace('_', ' ')} - {c.object.label}",
                  "qualifiers": c.qualifiers, "outcome": c.id in out} for c in r3.chain(card)]
        trials.append({"id": h, "T": r["meta"].get("as_of") or "", "registry_text": texts.get(h, ""), "chain": chain})
        by = {cv.id: cv for cv in cvs}
        key[h] = {"gate": e.gate, "balance_v36": e.chain_state,
                  "links": {cid: {"S": v[0], "F": v[3], "A": v[4],
                                  "record_pmids": sorted({x.record_id.replace("PMID:", "") for x in
                                                          ((by[cid].evidence + by[cid].counterevidence) if cid in by else [])})}
                            for cid, v in e.links.items()}}
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "pack_8_task.json").write_text(json.dumps({"task": "balance", "instructions": INSTRUCTIONS, "trials": trials},
                                                     indent=1, ensure_ascii=False) + "\n")
    (DIR / "pack_8_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    return {"trials": len(trials), "links": sum(len(t["chain"]) for t in trials),
            "size_kb": round((DIR / "pack_8_task.json").stat().st_size / 1024)}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

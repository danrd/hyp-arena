"""Argon pack 7: a second reader of novelty N (specs/novelty-check-2026-11-08.yaml). Free (no model calls).

    python -m scripts.pack7_novelty build     # -> longevity-kg reviews/argon-2026-11-08/pack_7_task.json + pack_7_key.json
"""
from __future__ import annotations

import json
import sys

from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from scripts.v34_check import CAL, PROS, parts

DIR = CAL.parents[1] / "reviews" / "argon-2026-11-08"
INSTRUCTIONS = """You are checking how NEW a research question was at a given date, the way a reviewer of a grant would.

Each item is a registered clinical trial (registry text), the date T, and the hypothesis CHAIN a model extracted from it:
links from the intervention to the outcome (delivery, engagement of a target, pathway, intermediate effect, outcome), each
as subject - relation - object with qualifiers. Use only papers published ON OR BEFORE T. Do not use anything later, even
if you know it.

Part 1, per trial, the novelty of the question on the OUTCOME link, by the CLOSEST paper published before T:
- new_context: the same intervention was already tested on this outcome in the same species, but in another population,
  age, sex or dose (the closest prior work differs only in context);
- translation: the same intervention on this outcome only in another species (e.g. mice, not humans);
- analog: only a related intervention (another compound or programme of the same kind) on this outcome;
- new_combination: nothing on the outcome link, but every link before it has published support (known pieces, untested whole);
- new_link: nothing on the outcome link, and at least one link before it has no paper at all, while at least one is supported;
- unknown: no relevant paper anywhere in the chain, or the chain is the outcome alone with nothing on it.
Take the level nearest the known when in doubt: a paper you cannot place exists more likely than not.
Give up to 3 defining PMIDs (published on or before T) that set the level. Also say known_result: true when the exact
result (same intervention, species, population, dose and outcome, positive) was already published before T, with its PMID.

Part 2, per link of the chain: level = new_context | translation | analog | new_link (no paper on this link before T), by the
closest paper before T, with up to 2 PMIDs.

Answer with one JSON object, nothing else:
{"task": "novelty", "trials": [{"id": "NCT...", "novelty": "...", "defining_pmids": ["..."], "known_result": false,
  "known_result_pmid": null, "links": [{"id": "c1", "level": "...", "pmids": ["..."]}], "note": "one sentence"}]}
"""


def build() -> dict:
    run = json.loads((PROS / "run_60.json").read_text())
    texts = {json.loads(l)["id"]: json.loads(l)["text"] for l in (PROS / "texts_60.jsonl").read_text().splitlines() if l.strip()}
    trials, key = [], {}
    for h, r in sorted(run.items()):
        it = r["items"][0]
        if not (it.get("card") and it.get("verification") and "v3" in it):
            continue
        card, cvs, _ = parts(it)
        with r32.method():
            N, src, levels = nv.novelty(card, cvs), nv.novelty_source(card, cvs), nv.link_levels(card, cvs)
        _, out = nv.slots(card)
        chain = [{"id": c.id, "type": c.link, "claim": f"{c.subject.label} - {c.relation.replace('_', ' ')} - {c.object.label}",
                  "qualifiers": c.qualifiers, "outcome": c.id in out} for c in r3.chain(card)]
        trials.append({"id": h, "T": r["meta"].get("as_of") or "", "registry_text": texts.get(h, ""), "chain": chain})
        recs = sorted({x.record_id.replace("PMID:", "") for cv in cvs for x in cv.evidence + cv.counterevidence})
        key[h] = {"N": N, "N_pmid": src, "link_levels": levels, "our_record_pmids": recs}
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "pack_7_task.json").write_text(json.dumps({"task": "novelty", "instructions": INSTRUCTIONS, "trials": trials},
                                                     indent=1, ensure_ascii=False) + "\n")
    (DIR / "pack_7_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    from collections import Counter
    return {"trials": len(trials), "links": sum(len(t["chain"]) for t in trials), "T": sorted({t["T"] for t in trials}),
            "our_N": Counter(k["N"] for k in key.values()),
            "size_kb": round((DIR / "pack_7_task.json").stat().st_size / 1024)}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1, default=str))

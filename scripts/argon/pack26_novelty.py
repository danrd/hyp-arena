"""Argon pack 26: a novelty gold where the high levels occur (specs/novelty/novelty-high-levels-2026-11-15.yaml).
Free, deterministic, no model call.

    python -m scripts.argon.pack26_novelty build   # longevity-kg/reviews/argon-2026-11-15/pack_26_task.json, pack_26_key.json

30 hypotheses that are not registry trials and whose card (working template, saved by the card benchmark:
reviews/argon-2026-11-13/bench_card_v2_ours_v17.json) has at least one mechanism step: every such Bio Arena and chat-written
text of card packs 19 and 20, plus the evolved versions with three or more steps (expected near the known: the low end of
the scale). Argon gets the text, one date T for all and the card's chain; not our records or levels (none are computed yet).
The texts of other authors stay in the private repository.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

KG = Path(__file__).resolve().parents[2].parent / "longevity-kg"
OUT = KG / "reviews" / "argon-2026-11-15"
SRC = KG / "reviews" / "argon-2026-11-13"
T = "2026-10-14"      # the earliest date a text of the set was written: no text is its own prior work

INSTRUCTIONS = """You are checking how NEW a research hypothesis was at a given date, the way a reviewer of a grant would.

Each item is a hypothesis text (some are in Russian), the date T, and the hypothesis CHAIN a model extracted from it: the
mechanism steps from the main factor to the outcome and the outcome(s), each as subject - relation - object with the
qualifiers the text states. Use only papers published ON OR BEFORE T. Check every PMID and its date in PubMed; never give a
PMID you have not checked. Judge the hypothesis as the chain states it; if the chain misreads the text, say so in the note
and still answer for the chain.

Part 1, per hypothesis: the novelty level, by the CLOSEST work published before T. A question already asked is not new,
whatever the answer was (a null result counts as prior work).
When the outcome link (the intervention or main factor on the outcome) HAS prior work:
- new_context: the same intervention and outcome were already studied in the claim's species, in another population, age,
  sex or dose;
- translation: the same intervention and outcome only in another species;
- analog: only a related intervention (another compound or programme of the same class) on this outcome;
- new_mechanism: the outcome link has prior work (any of the three above), but one step of the chain has NO paper, both its
  neighbours in the chain have published support, and PubMed holds fewer than 5 records before T on that step's own
  subject AND object. Give the level the outcome link would have without this step in outcome_level.
When the outcome link has NO prior work:
- new_combination: every step before the outcome has published support (known pieces, the whole chain untested);
- new_link: at least one step has no paper at all and at least one has published support.
- unknown: no relevant paper anywhere in the chain, or the chain is the outcome alone with nothing on it.
Order, from the known to the new: new_context < translation < analog < new_mechanism < new_combination < new_link.
When in doubt take the level nearer the known: a paper you cannot place exists more likely than not.
Give up to 3 defining PMIDs that set the level (the closest prior work first), and known_result: true when the exact result
(same intervention, species, population, dose and outcome, positive) was already published before T, with its PMID.

Part 2, per link of the chain:
- level: new_context | translation | analog | new_link (no paper on this link before T), by the closest paper, up to 2 PMIDs;
- supported: true when a published result before T supports the link (not only asks the question);
- for every link you call new_link: pubmed_query (the query you ran on the link's own subject AND object with their
  synonyms, no third term) and pubmed_count (the number of records before T). No count, no new_link: give "analog" or
  "unknown" instead.

Answer with one JSON object, nothing else:
{"task": "novelty_v2", "hypotheses": [{"id": "V01", "novelty": "...", "outcome_level": null, "defining_pmids": ["..."],
  "known_result": false, "known_result_pmid": null,
  "links": [{"id": "c1", "level": "...", "supported": false, "pmids": ["..."], "pubmed_query": null, "pubmed_count": null}],
  "note": "one sentence: what the closest prior work is and how it differs"}]}
"""


def _steps(card: dict) -> int:
    return sum(1 for c in card.get("claims", []) if c.get("link") and c["link"] != "outcome")


def build() -> dict:
    cards = json.loads((SRC / "bench_card_v2_ours_v17.json").read_text())
    keys = {**json.loads((SRC / "pack_19_key.json").read_text()), **json.loads((SRC / "pack_20_key.json").read_text())}
    rows = {r["id"]: r for r in map(json.loads, (KG / "hypothesis_db" / "rows.jsonl").read_text().splitlines())}
    picked = []
    for cid in sorted(cards):
        card, src = cards[cid].get("card") or {}, keys[cid]["source"]
        n = _steps(card)
        if (src in ("bioarena", "chatgpt") and n >= 1) or (src == "ours/evolution" and n >= 3):
            picked.append((cid, src, n, card))
    items, key = [], {}
    for i, (cid, src, n, card) in enumerate(picked, 1):
        vid, row = f"V{i:02d}", rows[keys[cid]["row"]]
        chain = [{"id": c["id"], "type": "outcome" if c["link"] == "outcome" else "step",
                  "claim": f"{c['subject']['label']} - {c['relation'].replace('_', ' ')} - {c['object']['label']}",
                  "qualifiers": c.get("qualifiers") or {}, "stated_as": c.get("stated_as")}
                 for c in card["claims"] if c.get("link")]
        items.append({"id": vid, "T": T, "text": row["text"], "chain": chain})
        key[vid] = {"card_pack_id": cid, "row": keys[cid]["row"], "source": src, "short": row.get("short"), "steps": n,
                    "written_on": row.get("written_on")}
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "pack_26_task.json"
    f.write_text(json.dumps({"task": "novelty_v2", "written_on": "2026-11-15", "instructions": INSTRUCTIONS,
                             "hypotheses": items}, indent=1, ensure_ascii=False) + "\n")
    (OUT / "pack_26_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    return {"hypotheses": len(items), "links": sum(len(i["chain"]) for i in items),
            "sources": Counter(v["source"] for v in key.values()), "steps": Counter(v["steps"] for v in key.values()),
            "kb": round(f.stat().st_size / 1024)}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1, default=str))

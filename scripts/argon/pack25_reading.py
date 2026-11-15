"""Argon pack 25: a fresh reading gold on outcome links, enriched for own studies of an intervention of the same class, with
the outcome-match field (specs/reading/class-findings-2026-11-15.yaml). Free, deterministic (hash order, no model call).

    python -m scripts.argon.pack25_reading build   # longevity-kg/reviews/argon-2026-11-15/pack_25{a,b}_task.json, pack_25_key.json

20 outcome links of trials that are in none of the earlier reading, search or card-reading packs (9, 13, 15, 16, 18) and not
the walkthrough trial, one link per trial, every abstract the link's saved search returned (at most 20). 14 links are
enriched, 6 random. Enriched = the most abstracts that PubMed types as a trial or a meta-analysis AND whose title shares no
word with the claim's subject: a study that does not name the claim's intervention is where a same-class finding sits (code
signals only, independent of our reader). Every third link (hash order) is a reserve: prompt examples are never taken from
this pack, and a second round of tuning, if one is needed, is scored on the reserve only.
"""
from __future__ import annotations

import json
import re
import sys

from hyparena.scoring import rules_v3 as r3
from hyparena.tools import pubmed
from scripts.argon import pack16_reading as p16
from scripts.common.reread_v11 import items

REV = p16.ROOT / "reviews"
OUT = REV / "argon-2026-11-15"
MAX_PAPERS, N_ENRICHED, N_RANDOM = 20, 14, 6
TRIAL_TYPES = {"Randomized Controlled Trial", "Meta-Analysis", "Clinical Trial", "Controlled Clinical Trial"}
EARLIER = ("argon-2026-11-08/pack_9_key.json", "argon-2026-11-08/pack_13_key.json", "argon-2026-11-11/pack_15_key.json",
           "argon-2026-11-12/pack_16_key.json", "argon-2026-11-12/pack_18_key.json")

_HEAD, _TAIL = p16.INSTRUCTIONS.split("- secondary_positive:")
INSTRUCTIONS = (_HEAD.replace(" For an ALTERNATIVE (a competing explanation of the\nhypothesis's effect) the hypothesis's own "
                              "outcome claim is given too.", "")
                + """- outcome_match (for "for" and "against"): where the quoted result sits relative to the outcome the CLAIM names:
  same (the claim's outcome itself, or the measure the claim names) | narrower (a specific measure or component of the
  claim's outcome: SPPB, gait speed or chair rise for "physical performance") | broader (a wider or composite outcome that
  only includes it: "overall health" for a named measure) | other (a different outcome, even if related: muscle mass for a
  claim about performance). A result on a broader or another outcome is normally finding "none" with none_reason
  other_outcome; give "for" or "against" with broader / other only when you still count it, and say why in context_note.
- outcome_measure: the verbatim words of the abstract that name the measure the quoted result is on (e.g. "SPPB",
  "6-minute walk distance"); null for none.
- secondary_positive: true when the claim's primary measure is null but a secondary measure of the same kind is positive.

Answer with one JSON object, nothing else:
{"task": "reading_gold_v3", "part": "A | B", "items": [{"id": "Q01", "papers": [{"pmid": "...", "finding": "...",
  "none_reason": null, "quote": null, "result_on_claim_measure": "...", "comparison": "...", "effect_phrase": null,
  "design": "...", "n_total": null, "n_quote": null, "intervention_match": "...", "context_differs": [], "context_note": "",
  "outcome_match": null, "outcome_measure": null, "secondary_positive": false}]}]}
""")


_TRIAL_ID = re.compile(r"\b(?:NCT\d{8}|ISRCTN\d+|NTR\d+|DRKS\d+|ACTRN\d+|UMIN\d+)\b")


def _units(text: str) -> set[str]:
    """Every registry trial id that occurs anywhere in a pack key (the keys of the packs are shaped differently)."""
    return set(_TRIAL_ID.findall(text))


def candidates() -> list[dict]:
    seen = {p16.H49}
    for f in EARLIER:
        seen |= _units((REV / f).read_text())
    out = []
    for pool in ("prospective", "calibration"):
        for h, as_of, card, _cvs, logs in items(pool):
            if h in seen:
                continue
            for c in r3.chain(card):
                ps = list(dict.fromkeys(logs.get(c.id) or []))[:MAX_PAPERS]
                if c.link == "outcome" and len(ps) >= 10:
                    out.append(dict(unit=h, pool=pool, T=as_of, claim_id=c.id, claim=p16._text(c), qualifiers=c.qualifiers,
                                    pmids=ps, subject=c.subject.label, hash=p16._h("pack25", h, c.id)))
    return out


def build() -> dict:
    cand = candidates()
    meta = pubmed.fetch(sorted({p for c in cand for p in c["pmids"]}))
    for c in cand:
        sw = p16._words(c["subject"])
        c["signal"] = sum(1 for p in c["pmids"] if TRIAL_TYPES & set(meta.get(p, {}).get("pubtypes", []))
                          and not sw & p16._words(meta.get(p, {}).get("title", "")))
    picked, used = [], set()

    def take(ordered, n, how):
        for c in ordered:
            if n and c["unit"] not in used:
                used.add(c["unit"])
                picked.append(dict(c, selection=how))
                n -= 1

    for pool in ("prospective", "calibration"):
        sub = [c for c in cand if c["pool"] == pool]
        take(sorted(sub, key=lambda c: (-c["signal"], c["hash"])), N_ENRICHED // 2, "enriched")
        take(sorted(sub, key=lambda c: c["hash"]), N_RANDOM // 2, "random")
    picked.sort(key=lambda c: c["hash"])
    task, key = {"A": [], "B": []}, {}
    for i, c in enumerate(picked, 1):
        qid = f"Q{i:02d}"
        papers = [{"pmid": p, "title": meta[p]["title"], "abstract": meta[p]["abstract"]}
                  for p in c["pmids"] if meta.get(p, {}).get("abstract")]
        task["A" if i % 2 else "B"].append({"id": qid, "T": c["T"], "kind": "claim", "claim": c["claim"],
                                            "qualifiers": c["qualifiers"], "papers": papers})
        key[qid] = {k: c[k] for k in ("unit", "pool", "claim_id", "selection", "signal", "T")} | {
            "reserve": i % 3 == 0, "pmids": [p["pmid"] for p in papers]}
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for part, its in task.items():
        f = OUT / f"pack_25{part.lower()}_task.json"
        f.write_text(json.dumps({"task": "reading_gold_v3", "part": part, "written_on": "2026-11-15",
                                 "instructions": INSTRUCTIONS, "items": its}, indent=1, ensure_ascii=False) + "\n")
        sizes[part] = {"links": len(its), "pairs": sum(len(i["papers"]) for i in its), "kb": round(f.stat().st_size / 1024)}
    (OUT / "pack_25_key.json").write_text(json.dumps(key, indent=1) + "\n")
    return {"candidates": len(cand), "candidate_trials": len({c["unit"] for c in cand}), "parts": sizes,
            "pools": {p: sum(v["pool"] == p for v in key.values()) for p in ("prospective", "calibration")},
            "reserve_links": sum(v["reserve"] for v in key.values()),
            "enriched_signal": sorted(v["signal"] for v in key.values() if v["selection"] == "enriched"),
            "random_signal": sorted(v["signal"] for v in key.values() if v["selection"] == "random")}


if __name__ == "__main__":
    print(json.dumps({"build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

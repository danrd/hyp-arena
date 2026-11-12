"""Argon pack 16: one full reading gold per (link, paper) for the reading benchmark (specs/benchmark-reading-2026-11-12.yaml).
Free, deterministic (hash order, no model call). Writes the task in two parts and the hidden key to the private repository.

    python -m scripts.pack16_reading build      # writes longevity-kg/reviews/argon-2026-11-12/pack_16{a,b}_task.json, pack_16_key.json
    python -m scripts.pack16_reading freeze     # SHA-256 of the gold files of packs 9, 13, 15 and 16 -> specs manifest (no texts)

Strata (20 links, all abstracts each link's last search returned, as our reader saw them):
  outcome 8 (4 random, 4 enriched), mechanism 5 (2 random, 3 enriched), alternative 5 (2 random, 3 enriched),
  repeat 2 (links of pack 9 with an own finding: Argon's agreement with itself).
Enriched = the most abstracts that PubMed types as RCT or meta-analysis AND whose title shares a word of the link's subject
(code signals only, independent of our reader). Pools alternate (prospective / calibration); one link per unit; pack 9 units
and H49 (walkthrough, tuned on) are left out except the repeats. Every third link of a stratum (hash order) is holdout.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from hyparena.card import rules_v3 as r3
from hyparena.tools import pubmed
from scripts.reread_v11 import items
from scripts.v34_check import CAL

ROOT = CAL.parents[1]                      # longevity-kg/hypothesis_sources -> longevity-kg
OUT = ROOT / "reviews" / "argon-2026-11-12"
PACK9 = ROOT / "reviews" / "argon-2026-11-08"
H49 = "NCT07726758"
MAX_PAPERS = 25
PLAN = {"outcome": (4, 4), "mechanism": (2, 3), "alternative": (2, 3)}
STOP = set("with from that this into their than over under after before about between among during without within "
           "exercise training program programme therapy treatment supplementation supplement intervention effect effects "
           "older adults patients people human".split())

INSTRUCTIONS = """You are building a gold standard for an evidence reader. Work only from the text you are given.

Each item is one CLAIM of a research hypothesis (subject - relation - object, with the qualifiers the claim itself states)
and every abstract a literature search returned for it before the date T. For an ALTERNATIVE (a competing explanation of the
hypothesis's effect) the hypothesis's own outcome claim is given too. Judge EVERY abstract; do not skip any; do not use
anything you know beyond the abstract.

For each abstract answer:
- finding: "for" (the study's OWN result supports the claim's relation), "against" (its own result for the claim's measure is
  no effect - not significant against control, or no change before-after - or the opposite direction), or "none".
  A significant but clinically small effect is "for", not "against". A null on ANOTHER measure of the same study is not
  "against" this claim. A result in another population, species, dose, or for a related intervention still counts as for /
  against: say so in intervention_match and context_differs.
- none_reason (only for "none"): no_own_result | background_or_consensus (a review or guideline sentence without data, e.g.
  "exercise is the mainstay of treatment") | other_outcome | other_intervention | protocol_only | other.
- quote: the shortest CONTIGUOUS span of the abstract, copied character for character, that gives the finding (null for none).
  Do not join sentences that are not next to each other; do not correct typos or symbols.
- result_on_claim_measure: better | no_difference | worse | not_reported - the study's own result for the claim's measure as
  analysed behind the quoted sentence (for a meta-analysis: the pooled result).
- comparison: between_groups | within_group | none - from the analysis behind the sentence, not from the number of arms
  ("X did not change in either group" is within_group).
- effect_phrase: the verbatim phrase with an effect size (OR, HR, SMD, %, mean difference with CI) or null.
- design: rct | non_randomised | observational | animal | cells | review | meta_analysis | other.
- n_total: the total number of participants or animals when the abstract states it as ONE number, else null (do not add
  group sizes); n_quote: the verbatim phrase.
- intervention_match, judged at the level at which the claim names the intervention: exact (the claim's intervention; a claim
  that names a kind, e.g. "resistance training", is matched exactly by any study of that kind) | class (the claim names a
  specific product or programme and the study used another member of its kind) | category (only the same broad category:
  another single nutrient for a multi-component formula, another exercise modality for a specific programme) | other
  (another intervention altogether).
- context_differs: a list from [population, age, sex, dose, comparator, species] - ONLY qualifiers the claim itself states
  and the study differs on; context_note: a few words.
- secondary_positive: true when the claim's primary measure is null but a secondary measure of the same kind is positive.
- for ALTERNATIVES only, distinguishing_part_shown: true when the finding shows the part of the alternative that differs from
  the hypothesis (for "attention and supervision explain the gain": an effect of attention itself, not that the exercise
  works); false otherwise.

Answer with one JSON object, nothing else:
{"task": "reading_gold_v2", "part": "A | B", "items": [{"id": "R01", "papers": [{"pmid": "...", "finding": "...",
  "none_reason": null, "quote": null, "result_on_claim_measure": "...", "comparison": "...", "effect_phrase": null,
  "design": "...", "n_total": null, "n_quote": null, "intervention_match": "...", "context_differs": [], "context_note": "",
  "secondary_positive": false, "distinguishing_part_shown": null}]}]}
"""


def _h(*xs) -> str:
    return hashlib.sha1("|".join(map(str, xs)).encode()).hexdigest()


def _text(c) -> str:
    return f"{c.subject.label} - {c.relation.replace('_', ' ')} - {c.object.label}"


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z\-]{4,}", s.lower()) if w not in STOP}


def candidates() -> list[dict]:
    pack9 = {(v["unit"], v["claim"]) for v in json.loads((PACK9 / "pack_9_key.json").read_text()).values()}
    p9_units = {u for u, _ in pack9}
    out = []
    for pool in ("prospective", "calibration"):
        for h, as_of, card, cvs, logs in items(pool):
            chain = {c.id: c for c in r3.chain(card)}
            alts = {a.id: a for a in card.proposed_alternatives}
            oc = card.outcome_claim
            for cid, ps in logs.items():
                if len(ps) < 10:
                    continue
                if cid in chain:
                    c = chain[cid]
                    stratum = "outcome" if c.link == "outcome" else "mechanism" if c.link else None
                    claim, quals = _text(c), c.qualifiers
                elif cid in alts:
                    a = alts[cid]
                    stratum, claim, quals = "alternative", _text(a), a.qualifiers
                else:
                    continue                                   # v2 mouse probes, premises outside the chain
                if not stratum:
                    continue
                repeat = (h, cid) in pack9
                if (h in p9_units and not repeat) or h == H49 and not repeat:
                    continue
                out.append(dict(unit=h, pool=pool, T=as_of, claim_id=cid, stratum="repeat" if repeat else stratum,
                                claim=claim, qualifiers=quals, pmids=list(dict.fromkeys(ps))[:MAX_PAPERS],
                                hypothesis_outcome=_text(oc) if (cid in alts and oc) else None,
                                subject=(chain.get(cid) or alts.get(cid)).subject.label))
    return out


def build() -> dict:
    cand = candidates()
    meta = pubmed.fetch(sorted({p for c in cand for p in c["pmids"]}))
    for c in cand:
        sw = _words(c["subject"])
        c["signal"] = sum(1 for p in c["pmids"]
                          if {"Randomized Controlled Trial", "Meta-Analysis"} & set(meta.get(p, {}).get("pubtypes", []))
                          and sw & _words(meta.get(p, {}).get("title", "")))
        c["hash"] = _h("pack16", c["unit"], c["claim_id"])
    picked, used = [], set()

    def take(pool_list, n, how):
        k = 0
        for c in pool_list:
            if k == n:
                break
            if c["unit"] in used:
                continue
            used.add(c["unit"])
            picked.append(dict(c, selection=how))
            k += 1

    # repeats first: pack-9 links with an own finding in Argon's answer
    ans9 = json.loads((PACK9 / "pack_9_answer.json").read_text())
    key9 = json.loads((PACK9 / "pack_9_key.json").read_text())
    pos9 = {(key9[i["id"]]["unit"], key9[i["id"]]["claim"]) for i in ans9["items"]
            if any(p["finding"] != "none" for p in i["papers"])}
    take(sorted([c for c in cand if c["stratum"] == "repeat" and (c["unit"], c["claim_id"]) in pos9],
                key=lambda c: c["hash"]), 2, "repeat")
    for stratum, (n_rand, n_enr) in PLAN.items():
        cs = [c for c in cand if c["stratum"] == stratum]
        for pool_name in ("prospective", "calibration"):
            sub = [c for c in cs if c["pool"] == pool_name]
            half = lambda n: (n + (pool_name == "prospective")) // 2
            take(sorted(sub, key=lambda c: (-c["signal"], c["hash"])), half(n_enr), "enriched")
            take(sorted(sub, key=lambda c: c["hash"]), half(n_rand), "random")
    # holdout: every third link of a stratum in hash order (repeats never)
    for stratum in PLAN:
        for i, c in enumerate(sorted([c for c in picked if c["stratum"] == stratum], key=lambda c: c["hash"])):
            c["holdout"] = i % 3 == 2
    picked.sort(key=lambda c: c["hash"])
    task, key = {"A": [], "B": []}, {}
    for i, c in enumerate(picked, 1):
        rid = f"R{i:02d}"
        papers = [{"pmid": p, "title": meta[p]["title"], "abstract": meta[p]["abstract"]}
                  for p in c["pmids"] if meta.get(p, {}).get("abstract")]
        item = {"id": rid, "T": c["T"], "kind": "alternative" if c["stratum"] == "alternative" else "claim",
                "claim": c["claim"], "qualifiers": c["qualifiers"], "papers": papers}
        if c["hypothesis_outcome"]:
            item["hypothesis_outcome_claim"] = c["hypothesis_outcome"]
        task["A" if i % 2 else "B"].append(item)
        key[rid] = {k: c[k] for k in ("unit", "pool", "claim_id", "stratum", "selection", "signal", "T")} | {
            "holdout": c.get("holdout", False), "pmids": [p["pmid"] for p in papers]}
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for part, its in task.items():
        f = OUT / f"pack_16{part.lower()}_task.json"
        f.write_text(json.dumps({"task": "reading_gold_v2", "part": part, "written_on": "2026-11-12",
                                 "instructions": INSTRUCTIONS, "items": its}, indent=1, ensure_ascii=False) + "\n")
        sizes[part] = {"links": len(its), "pairs": sum(len(i["papers"]) for i in its), "kb": round(f.stat().st_size / 1024)}
    (OUT / "pack_16_key.json").write_text(json.dumps(key, indent=1) + "\n")
    strata = {}
    for v in key.values():
        strata.setdefault(f"{v['stratum']}/{v['selection']}", []).append(len(v["pmids"]))
    return {"parts": sizes, "strata": {k: {"links": len(v), "pairs": sum(v)} for k, v in strata.items()},
            "holdout_links": sum(v["holdout"] for v in key.values()),
            "enriched_signal": sorted(v["signal"] for v in key.values() if v["selection"] == "enriched"),
            "random_signal": sorted(v["signal"] for v in key.values() if v["selection"] == "random")}


def freeze() -> dict:
    files = {"pack_9": ["argon-2026-11-08/pack_9_task.json", "argon-2026-11-08/pack_9_key.json", "argon-2026-11-08/pack_9_answer.json"],
             "pack_13": ["argon-2026-11-08/pack_13_task.json", "argon-2026-11-08/pack_13_key.json", "argon-2026-11-08/pack_13_answer.json"],
             "pack_15": ["argon-2026-11-11/pack_15_task.json", "argon-2026-11-11/pack_15_key.json", "argon-2026-11-11/pack_15_answer.json"],
             "pack_16": ["argon-2026-11-12/pack_16a_task.json", "argon-2026-11-12/pack_16b_task.json", "argon-2026-11-12/pack_16_key.json"]}
    rev = ROOT / "reviews"
    return {k: {f: hashlib.sha256((rev / f).read_bytes()).hexdigest() for f in fs if (rev / f).exists()} for k, fs in files.items()}


if __name__ == "__main__":
    print(json.dumps({"build": build, "freeze": freeze}[sys.argv[1] if len(sys.argv) > 1 else "build"](), indent=1))

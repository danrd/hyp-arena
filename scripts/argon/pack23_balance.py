"""Argon pack 23 (specs/scoring/balance-pairs-2026-11-15.yaml): pairs of records of one link, ordered by an outside reader
as evidence about the claim, against the order of the current record weights (v3.6 with the GRADE certainty of a
meta-analysis). The successor of pack 5 (80 pairs, 2026-11-08): more pairs, the current weights, a stratum for a
meta-analysis against a trial, and three parts that each fit one message.

    python -m scripts.argon.pack23_balance build      # free: task parts, the hidden key
    python -m scripts.argon.pack23_balance score      # free, after the answers are saved
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from scripts.common.v34_check import CAL

DIR = CAL.parents[1] / "reviews" / "argon-2026-11-15"
PACK5 = CAL.parents[1] / "reviews" / "argon-2026-11-08"
FACTORS = ("design", "precision", "effect", "comparison", "context")
PER_STRATUM = 25            # design, precision, effect, comparison, context, meta_vs_trial, near_tie
REPEATS = 20                # pairs shown again with A and B swapped
PER_LINK = 4
PARTS = 3
NEAR_TIE = 0.15             # |log wA/wB| under it: a near-tie
TIE = 0.1                   # |log wA/wB| under it counts as "equal" in the measures

INSTRUCTIONS = """You are reviewing evidence the way an evidence-based-medicine reviewer would (GRADE-style judgement).

Each item is a CLAIM from a hypothesis about an intervention in older adults, and TWO PUBLISHED RECORDS (A and B) that a
reader found for that claim: PMID, title, abstract, the sentence the reader took as the finding (quote) and whether the
reader read it as evidence FOR or AGAINST the claim.

Part 1, pairs. For each pair decide which record is STRONGER EVIDENCE ABOUT THE CLAIM, whatever its direction: which one
should move a careful reviewer's belief in the claim more (up if it is for, down if it is against). Consider the study
design (and for a meta-analysis the certainty of its evidence), its size, the comparison, the size of the effect, how
directly it tests the claim's intervention, population and outcome, and the risk of bias (blinding, placebo or sham,
self-reported outcomes). Answer A, B or equal; equal when you would not order them. Give a confidence 1 (unsure) to 3
(clear) and up to three reason codes, the first being the main one: design, certainty, sample_size, effect_size,
comparison, directness_intervention, directness_population, directness_outcome, risk_of_bias, finding_misread, other. Use
finding_misread when the reader's quote or its for / against reading is wrong. Some pairs appear twice with A and B
swapped; judge each item on its own.

Part 2, records. For each record id in `records`, label from the title and abstract:
- design: rct | non_randomised | observational | animal | cells | review | meta_analysis | other
- n_total: the number of participants (or animals) analysed, if the abstract states one number; else null
- context, relative to the claim it belongs to (see `claim_of_record`): exact = the intervention the claim names, in the
  claim's population (a claim that names a kind is matched exactly by any study of that kind); adjacent = the same
  intervention but another population, age, sex, species, dose or schedule, or another comparator than the claim fixes
  (only qualifiers the claim states count); class = the claim names a specific product, compound or programme and the
  study used another member of its kind; none = another intervention altogether, or no result on the claim
- certainty: for a meta-analysis, the certainty of evidence it states (high | moderate | low | very_low | not_stated);
  null for other designs
- effect_phrase: the verbatim phrase giving the size of the effect (a ratio, a standardised difference, a percent or mean
  difference with its interval), or null

This is part {part} of {parts}; the parts are independent. Answer with one JSON object, nothing else:
{{"task": "pack_23_{part}", "pairs": [{{"id": "P001", "stronger": "A" | "B" | "equal", "confidence": 1 | 2 | 3,
  "reasons": ["design", ...], "note": "one sentence"}}], "records": [{{"id": "R001", "design": "...", "n_total": 120 | null,
  "context": "...", "certainty": "..." | null, "effect_phrase": "..." | null}}]}}"""


def sha(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def factors_v36(rec, claim, against: bool) -> dict | None:
    """The factors of hyparena.scoring.rules_v32.record_weight_v36, each as its multiplier (their product is the weight)."""
    from hyparena.scoring import rules_v3 as r3, rules_v32 as r32, v3_levels as lv
    from hyparena.reading.review_kind import certainty_factor
    if not r3.usable(rec, r32.VARIANT_BASE):
        return None
    ctx = r32.context_v34(rec, claim)
    if ctx is None:
        return None
    pre = claim.link in r3.PRECLINICAL_LINKS
    design = r3.record_design(rec)
    d = r32.DESIGN_GRADE3.get(design, 0.25) if (r3.human_claim(claim) and not pre) else lv.design_weight(design, False)
    if design == "meta_analysis" and r32.META_CERTAINTY:
        d *= certainty_factor(rec.certainty)
    if against:
        p, e = r32.null_power(rec.n_total, rec.comparison), 1.0
    else:
        p = r32.PRECLINICAL_PRECISION if pre else r32.precision(rec.n_total)
        e = 1.0 if r32.effect_weight(rec, False) >= r32.EFFECT_FULL_FROM - 1e-9 else 0.5
    return {"design": d, "precision": p, "effect": e, "comparison": 1.0 if rec.comparison == "between_groups" else 0.5,
            "context": 0.5 if ctx == "adjacent" else 1.0, "design_label": design, "ctx": ctx}


def weight(f: dict) -> float:
    return math.prod(f[k] for k in FACTORS)


def pool() -> list[dict]:
    from scripts.common.v34_check import PROS, parts
    out = []
    for h, r in json.loads((PROS / "run_60.json").read_text()).items():
        it = r["items"][0]
        if not (it.get("card") and it.get("verification") and "v3" in it):
            continue
        card, cvs, _ = parts(it, h)
        claims = {c.id: c for c in card.claims}
        for cv in cvs:
            claim = claims.get(cv.id)
            if claim is None:
                continue
            for side, recs in (("for", cv.evidence), ("against", cv.counterevidence)):
                for rec in recs:
                    f = factors_v36(rec, claim, side == "against")
                    if f is None or weight(f) <= 0:
                        continue
                    out.append({"unit": h, "claim": cv.id, "claim_obj": claim, "side": side, "rec": rec,
                                "pmid": rec.record_id.replace("PMID:", ""), "f": f, "w": weight(f)})
    return out


def _pack5_pairs() -> set:
    key = json.loads((PACK5 / "pack_5_key.json").read_text())
    task = json.loads((PACK5 / "pack_5_task.json").read_text())
    pm = {i: r["pmid"] for i, r in task["records"].items()}
    tp = {p["id"]: p for p in task["pairs"]}
    return {frozenset((pm[tp[k["id"]]["A"]], pm[tp[k["id"]]["B"]])) | {tuple(k["link"])} for k in key["pairs"]}


def build() -> dict:
    from hyparena.tools import pubmed
    rows = pool()
    done5 = _pack5_pairs()
    links = defaultdict(list)
    for r in rows:
        links[(r["unit"], r["claim"])].append(r)
    cand = []
    for key, rs in links.items():
        for a, b in itertools.combinations(rs, 2):
            if a["pmid"] == b["pmid"] or (frozenset((a["pmid"], b["pmid"])) | {key}) in done5:
                continue
            dl = abs(math.log(a["w"] / b["w"]))
            if {a["f"]["design_label"], b["f"]["design_label"]} == {"meta_analysis", "rct"}:
                stratum = "meta_vs_trial"
            elif dl < NEAR_TIE:
                stratum = "near_tie"
            else:
                stratum = max(FACTORS, key=lambda k: abs(math.log(a["f"][k] / b["f"][k])))
            cand.append({"key": key, "a": a, "b": b, "stratum": stratum, "h": sha(f"pack23|{a['pmid']}|{b['pmid']}|{key}")})
    cand.sort(key=lambda c: c["h"])
    want = {s: PER_STRATUM for s in (*FACTORS, "meta_vs_trial", "near_tie")}
    picked, per_link = [], Counter()
    for c in cand:
        if want[c["stratum"]] > 0 and per_link[c["key"]] < PER_LINK:
            picked.append(c); want[c["stratum"]] -= 1; per_link[c["key"]] += 1
    short = {k: v for k, v in want.items() if v > 0}
    target = PER_STRATUM * len(want)
    for c in cand:                                   # the shortfall of a stratum filled from the others
        if len(picked) >= target:
            break
        if c not in picked and per_link[c["key"]] < PER_LINK:
            picked.append(c); per_link[c["key"]] += 1
    rid, recs = {}, {}
    for c in picked:
        for r in (c["a"], c["b"]):
            k = (r["pmid"], r["unit"], r["claim"], r["rec"].quote)
            if k not in rid:
                rid[k] = f"R{len(rid) + 1:03d}"; recs[rid[k]] = r
    cid, claims = {}, {}
    for c in picked:
        if c["key"] not in cid:
            cid[c["key"]] = f"C{len(cid) + 1:02d}"
            cl = c["a"]["claim_obj"]
            claims[cid[c["key"]]] = {"subject": cl.subject.label, "relation": cl.relation, "object": cl.object.label,
                                     "qualifiers": cl.qualifiers}
    R = lambda r: rid[(r["pmid"], r["unit"], r["claim"], r["rec"].quote)]
    items = [{"src": i, "claim": cid[c["key"]], "A": R(c["a"]), "B": R(c["b"]), "swapped": False} for i, c in enumerate(picked)]
    items += [{**items[i], "A": items[i]["B"], "B": items[i]["A"], "swapped": True} for i in range(REPEATS)]
    items.sort(key=lambda x: sha(f"pack23-order|{x['src']}|{x['swapped']}"))
    for n, x in enumerate(items, 1):
        x["id"] = f"P{n:03d}"
    meta = pubmed.fetch(sorted({r["pmid"] for r in recs.values()}))
    DIR.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for part in range(1, PARTS + 1):
        its = items[part - 1::PARTS]
        used = sorted({x[k] for x in its for k in ("A", "B")})
        task = {"task": f"pack_23_{part}", "instructions": INSTRUCTIONS.format(part=part, parts=PARTS),
                "claims": {c: claims[c] for c in sorted({x["claim"] for x in its})},
                "records": {i: {"pmid": recs[i]["pmid"], "title": meta.get(recs[i]["pmid"], {}).get("title", ""),
                                "abstract": meta.get(recs[i]["pmid"], {}).get("abstract", ""), "quote": recs[i]["rec"].quote,
                                "reader_reading": recs[i]["side"]} for i in used},
                "claim_of_record": {i: cid[(recs[i]["unit"], recs[i]["claim"])] for i in used},
                "pairs": [{"id": x["id"], "claim": x["claim"], "A": x["A"], "B": x["B"]} for x in its]}
        f = DIR / f"pack_23_{part}_task.json"
        f.write_text(json.dumps(task, indent=1, ensure_ascii=False) + "\n")
        sizes[f.name] = {"pairs": len(its), "records": len(used), "kb": round(f.stat().st_size / 1024)}
    key = {"pairs": [{"id": x["id"], "src": x["src"], "swapped": x["swapped"], "stratum": picked[x["src"]]["stratum"],
                      "link": list(picked[x["src"]]["key"]), "w": [round(recs[x["A"]]["w"], 4), round(recs[x["B"]]["w"], 4)],
                      "factors": [{k: recs[x[s]]["f"][k] for k in FACTORS} for s in ("A", "B")]} for x in items],
           "records": {i: {"unit": r["unit"], "claim": r["claim"], "side": r["side"], "design": r["rec"].design,
                           "n_total": r["rec"].n_total, "context": r["f"]["ctx"], "certainty": getattr(r["rec"], "certainty", None),
                           "effect_reported": r["rec"].effect_reported} for i, r in recs.items()},
           "strata_short": short}
    (DIR / "pack_23_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False, default=str) + "\n")
    return {"items": len(items), "unique_pairs": len(picked), "records": len(recs), "claims": len(claims),
            "strata": dict(Counter(c["stratum"] for c in picked)), "strata_short": short, "parts": sizes}


def score() -> dict:
    from scipy.stats import kendalltau
    key = {p["id"]: p for p in json.loads((DIR / "pack_23_key.json").read_text())["pairs"]}
    ans = {}
    for part in range(1, PARTS + 1):
        f = DIR / f"pack_23_{part}_answer.json"
        if f.exists():
            ans.update({p["id"]: p for p in json.loads(f.read_text())["pairs"]})
    arg = lambda i: {"A": 1, "B": -1, "equal": 0}[ans[i]["stronger"]]
    ours = lambda i: (lambda d: 0 if abs(d) < TIE else (1 if d > 0 else -1))(math.log(key[i]["w"][0] / key[i]["w"][1]))
    main = [i for i in key if not key[i]["swapped"] and i in ans]
    x, y = [arg(i) for i in main], [ours(i) for i in main]
    ne = [(a, b) for a, b in zip(x, y) if a and b]
    per = defaultdict(list)
    for i in main:
        if arg(i) and ours(i):
            per[key[i]["stratum"]].append(arg(i) == ours(i))
    by_src = {(key[i]["src"], key[i]["swapped"]): i for i in key if i in ans}
    rep = [(by_src[(s, False)], by_src[(s, True)]) for s, sw in by_src if sw and (s, False) in by_src]
    agree = sum(arg(a) == -arg(b) for a, b in rep)
    reasons = Counter(ans[i]["reasons"][0] for i in main if ans[i].get("reasons"))
    out = {"pairs": len(main), "tau_b": round(kendalltau(x, y, variant="b").statistic, 3),
           "concordance_non_tied": round(sum(a == b for a, b in ne) / len(ne), 3) if ne else None, "n_non_tied": len(ne),
           "per_stratum": {k: f"{sum(v)} of {len(v)}" for k, v in sorted(per.items())},
           "argon_equal": sum(a == 0 for a in x), "repeats_agree": f"{agree} of {len(rep)}", "main_reasons": dict(reasons)}
    (DIR / "pack_23_score.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["build", "score"])
    print(json.dumps(build() if ap.parse_args().cmd == "build" else score(), indent=1, default=str))


if __name__ == "__main__":
    main()

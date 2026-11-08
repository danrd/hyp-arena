"""specs/record-weight-2026-11-08.yaml: the record weight and the fold of for / against, step by step. Free (no model calls;
PubMed E-utilities for years and abstracts, cached in data/cache/pubmed).

    python -m scripts.record_weight_check step1          # -> calibration/record_weight_step1.json, prints the summary
    python -m scripts.record_weight_check step2-sample   # -> calibration/record_weight_context_check.jsonl (to label by hand)
    python -m scripts.record_weight_check step2-score    # agreement of the hand labels with the verifier
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections import Counter

import numpy as np
from scipy.stats import spearmanr

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from scripts.ablation import units
from scripts.v34_check import CAL, PROS, parts

FACTORS = ("design", "precision", "effect", "comparison", "context")
CHECK = CAL / "record_weight_context_check.jsonl"


def pmid(rec) -> str:
    m = re.fullmatch(r"PMID:(\d+)", rec.record_id or "")
    return m.group(1) if m else ""


def factors(rec, claim, against: bool) -> dict | None:
    """The v3.5 factors (null by power) of one record; None when it does not count."""
    f = r32.weight_factors(rec, claim, against, v34=True)
    if not f:
        return None
    out = {k: [f[k][0], float(f[k][1])] for k in FACTORS}
    if against:                                  # v3.5 (B): the power of the study replaces precision x effect
        out["precision"] = [rec.n_total, r32.null_power(rec.n_total, rec.comparison)]
        out["effect"] = ["against", 1.0]
    out["w"] = math.prod(out[k][1] for k in FACTORS)
    return out if out["w"] > 0 else None


def pool() -> list[dict]:
    """Every counting record of the declared claims: calibration (73) and prospective (60)."""
    items = [("calibration", u["id"], u["card"], u["cvs"]) for u in units()]
    for h, r in json.loads((PROS / "run_60.json").read_text()).items():
        it = r["items"][0]
        if it.get("card") and it.get("verification") and "v3" in it:
            card, cvs, _ = parts(it)
            items.append(("prospective", h, card, cvs))
    out = []
    for sample, uid, card, cvs in items:
        claims = {c.id: c for c in card.claims}
        for cv in cvs:
            claim = claims.get(cv.id)
            if claim is None:
                continue
            for side, recs in (("for", cv.evidence), ("against", cv.counterevidence)):
                for rec in recs:
                    f = factors(rec, claim, side == "against")
                    if f is None:
                        continue
                    out.append({"sample": sample, "unit": uid, "claim": cv.id, "link": claim.link,
                                "pre": claim.link in r3.PRECLINICAL_LINKS, "side": side, "rec": rec, "claim_obj": claim,
                                "group": r32.group_key(rec), "pmid": pmid(rec), **f})
    return out


def spread(rows: list[dict]) -> dict:
    if len(rows) < 3:
        return {"n": len(rows)}
    L = {k: np.log([r[k][1] for r in rows]) for k in FACTORS}
    lw = sum(L.values())
    var = float(lw.var())
    res = {"n": len(rows), "w_median": round(float(np.exp(np.median(lw))), 3),
           "w_p10_p90": [round(float(np.exp(np.percentile(lw, q))), 3) for q in (10, 90)]}
    for k in FACTORS:
        x = np.array([r[k][1] for r in rows])
        share = float(np.cov(L[k], lw, ddof=0)[0, 1] / var) if var > 0 else 0.0
        res[k] = {"mean": round(float(x.mean()), 3), "min": round(float(x.min()), 3), "max": round(float(x.max()), 3),
                  "share_of_spread": round(share, 3)}
    return res


def level(k: str, r: dict) -> str:
    lab, v = r[k]
    if k == "precision":
        if r["side"] == "against":
            return "power " + ("n unknown" if lab is None else "<50" if lab < 50 else "50-299" if lab < 300 else ">=300")
        if r["pre"]:
            return "constant 1/2 (before outcome)"
        return "n unknown" if lab is None else "<50" if lab < 50 else "50-299" if lab < 300 else ">=300"
    if k == "design":
        return f"{lab} ({'before outcome' if r['pre'] else 'outcome link'}) = {v:.2f}"
    if k == "effect" and r["side"] == "for":
        return f"{lab} -> {'class' if abs(v * 4 - round(v * 4)) < 1e-9 else 'continuous'}"
    return f"{lab}"


def step1() -> dict:
    rows = pool()
    out = {"records": len(rows), "by_sample": Counter(r["sample"] for r in rows),
           "by_side": Counter(r["side"] for r in rows), "by_link": Counter(r["link"] for r in rows),
           "links": len({(r["unit"], r["claim"]) for r in rows})}
    out["spread"] = {"all": spread(rows), "for": spread([r for r in rows if r["side"] == "for"]),
                     "against": spread([r for r in rows if r["side"] == "against"]),
                     "outcome_link": spread([r for r in rows if not r["pre"]]),
                     "before_outcome": spread([r for r in rows if r["pre"]])}
    out["levels"] = {k: {side: Counter(level(k, r) for r in rows if r["side"] == side).most_common()
                         for side in ("for", "against")} for k in FACTORS}
    L = {k: [math.log(r[k][1]) for r in rows] for k in FACTORS}
    out["spearman_log_factors"] = {f"{a}~{b}": round(float(spearmanr(L[a], L[b]).statistic), 3)
                                   for i, a in enumerate(FACTORS) for b in FACTORS[i + 1:]
                                   if len(set(L[a])) > 1 and len(set(L[b])) > 1}
    out["missing"] = {"n_unknown": sum(r["rec"].n_total is None for r in rows),
                      "effect_unclear_for": sum(r["side"] == "for" and r["rec"].effect_class == "unclear" for r in rows),
                      "comparison_unknown": sum(r["rec"].comparison == "unknown" for r in rows),
                      "design_unknown_or_other": sum(r3.record_design(r["rec"]) in ("unknown", "other") for r in rows),
                      "no_pmid": sum(not r["pmid"] for r in rows)}
    # the fold: how much the independence groups change F and A
    folded = Counter()
    for side in ("for", "against"):
        by_link: dict = {}
        for r in rows:
            if r["side"] == side:
                by_link.setdefault((r["unit"], r["claim"]), {}).setdefault(r["group"], []).append(r["w"])
        raw = sum(sum(ws) for g in by_link.values() for ws in g.values())
        fold = sum(sorted(ws)[-1] + r32.FOLD_REST * (sum(ws) - max(ws)) for g in by_link.values() for ws in g.values())
        folded[f"{side}_records_in_multi_record_groups"] = sum(len(ws) for g in by_link.values() for ws in g.values() if len(ws) > 1)
        folded[f"{side}_folded_over_raw_sum"] = round(fold / raw, 3) if raw else None
    out["fold"] = dict(folded)
    # availability of the candidate new factors (step 6), records for only
    fr = [r for r in rows if r["side"] == "for"]
    flags = Counter(f for r in fr for f in r["rec"].flags)
    out["availability_for_step6"] = {
        "records_for": len(fr), "flags": dict(flags.most_common()),
        "marker_validation": Counter(r["rec"].marker_validation for r in fr),
        "endpoint": Counter(r["rec"].endpoint for r in fr),
        "with_pmid": sum(bool(r["pmid"]) for r in fr)}
    (CAL / "record_weight_step1.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str) + "\n")
    return out


def sha(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def step2_sample() -> list[dict]:
    """40 records stratified by the verifier's context label (25 class, 10 adjacent, 5 exact), by SHA-1 order."""
    from hyparena.tools import pubmed
    rows = pool()
    want = {"class": 25, "adjacent": 10, "exact": 5}
    picked = []
    for lab, k in want.items():
        cand = sorted((r for r in rows if r["context"][0] == lab and r["pmid"]),
                      key=lambda r: sha(f"{r['rec'].record_id}|{r['unit']}|{r['claim']}"))
        seen = set()
        for r in cand:
            key = (r["pmid"], r["unit"], r["claim"])
            if key in seen:
                continue
            seen.add(key)
            picked.append(r)
            if sum(p["context"][0] == lab for p in picked) == k:
                break
    abstracts = pubmed.fetch(sorted({r["pmid"] for r in picked}))
    out = []
    for i, r in enumerate(picked, 1):
        c, rec = r["claim_obj"], r["rec"]
        a = abstracts.get(r["pmid"], {})
        out.append({"n": i, "sample": r["sample"], "unit": r["unit"], "claim_id": r["claim"], "link": r["link"],
                    "claim": {"subject": c.subject.label, "relation": c.relation, "object": c.object.label,
                              "qualifiers": c.qualifiers},
                    "pmid": r["pmid"], "side": r["side"], "design": rec.design, "quote": rec.quote,
                    "title": a.get("title", ""), "abstract": a.get("abstract", ""),
                    "verifier": {"context": r["context"][0], "intervention_match": rec.qualifiers_match.get("intervention_match", ""),
                                 "qualifiers_match": rec.qualifiers_match},
                    "hand": {"context": "", "note": ""}})
    order = sorted(out, key=lambda x: sha(f"blind|{x['n']}"))          # labelled in an order that hides the stratum
    CHECK.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in order))
    return order


def kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n ** 2
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def step2_score() -> dict:
    xs = [json.loads(l) for l in CHECK.read_text().splitlines() if l.strip()]
    lab = [x for x in xs if x["hand"]["context"]]
    pairs = [(x["verifier"]["context"], x["hand"]["context"]) for x in lab]
    cls = [h for v, h in pairs if v == "class"]
    w = {"exact": 1, "adjacent": 2 / 3, "class": 1 / 3, "none": 0}
    ratio = [w[h] / w[v] for v, h in pairs]
    return {"labelled": len(lab), "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3), "kappa": kappa(pairs),
            "confusion": Counter(f"{v}->{h}" for v, h in pairs).most_common(),
            "class_should_be": Counter(cls), "class_should_be_exact_share": round(cls.count("exact") / len(cls), 3) if cls else None,
            "weight_ratio_hand_over_verifier": {"mean": round(float(np.mean(ratio)), 3), "median": round(float(np.median(ratio)), 3)}}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "step1"
    res = {"step1": step1, "step2-sample": lambda: f"{len(step2_sample())} records -> {CHECK}", "step2-score": step2_score}[cmd]()
    print(json.dumps(res, indent=1, ensure_ascii=False, default=str))

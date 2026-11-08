"""specs/record-weight-2026-11-08.yaml: the record weight and the fold of for / against, step by step. Free (no model calls;
PubMed E-utilities for years and abstracts, cached in data/cache/pubmed).

    python -m scripts.record_weight_check step1          # -> calibration/record_weight_step1.json, prints the summary
    python -m scripts.record_weight_check step2-sample   # -> calibration/record_weight_context_check.jsonl (to label by hand)
    python -m scripts.record_weight_check step2-score    # agreement of the hand labels with the verifier
    python -m scripts.record_weight_check step4          # each factor: drop / flatten / coarsen (menu step4_factors)
    python -m scripts.record_weight_check step67         # risk of bias and subgroup on top of the candidate; the fold
    python -m scripts.record_weight_check pack5          # pack 5 for Argon (R4), to longevity-kg reviews/argon-2026-11-08
    python -m scripts.record_weight_check step3          # references R1, R2 (years from PubMed), R3; current rules, both context variants
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import random
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager

import numpy as np
from scipy.stats import spearmanr

from hyparena.backtest import tied_auc
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from scripts.ablation import units
from scripts.v34_check import CAL, PROS, parts

_CTX = r32.context_v34_verifier      # the verifier's label as is (the method uses the claim-qualifier rule since 2026-11-08)


def context_claim_qualifiers(rec, claim):
    """Context variant claim_qualifiers (spec): a "no" counts only on a qualifier the claim fixes."""
    q = claim.qualifiers or {}

    def fixed(k: str) -> bool:
        if k == "population":
            return any(q.get(x) for x in ("population", "disease", "age_at_start"))
        if k == "species":
            return bool(q.get("species")) or r3.human_claim(claim)
        return bool(q.get(k))
    qm = {k: v for k, v in rec.qualifiers_match.items() if k == "intervention_match" or v != "no" or fixed(k)}
    return _CTX(rec.model_copy(update={"qualifiers_match": qm}), claim)


@contextmanager
def context_variant(name: str):
    """'verifier' (v3.5 as is) or 'claim_qualifiers'; patches the context used by record_weight and weight_factors."""
    method = r32.context_v34
    r32.context_v34 = _CTX if name == "verifier" else context_claim_qualifiers
    try:
        yield
    finally:
        r32.context_v34 = method


VARIANTS = ("verifier", "claim_qualifiers")
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


@context_variant("verifier")      # as recorded in the spec (the verifier's context label)
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


@context_variant("verifier")      # as recorded in the spec (the verifier's context label)
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


def with_years(rows: list[dict]) -> list[dict]:
    from hyparena.tools import pubmed
    meta = pubmed.fetch(sorted({r["pmid"] for r in rows if r["pmid"]}))
    for r in rows:
        y = (meta.get(r["pmid"], {}).get("year") or "")[:4]
        r["year"] = int(y) if y.isdigit() else None
        r["dsg"] = r3.record_design(r["rec"])
    return rows


def link_state(rows: list[dict], c: float = r32.C_ANCHOR) -> float:
    """s = 2S - 1 of a set of records of one link (v3.5 Beta, fold by independence group)."""
    side = {"for": defaultdict(list), "against": defaultdict(list)}
    for r in rows:
        side[r["side"]][r["group"]].append(r["w"])
    F, A = (sum(max(ws) + r32.FOLD_REST * (sum(ws) - max(ws)) for ws in side[k].values()) for k in ("for", "against"))
    return 2 * (c * F + 1) / (c * (F + A) + 2) - 1


def build_refs(rows: list[dict]) -> dict:
    links = defaultdict(list)
    for r in rows:
        links[(r["unit"], r["claim"])].append(r)
    r1, r2, cnt = [], [], Counter()
    for key, rs in links.items():
        dated = [r for r in rs if r["year"]]
        cnt["records_without_year"] += len(rs) - len(dated)
        mas = [r for r in dated if r["dsg"] == "meta_analysis"]
        if mas:
            cnt["links_with_meta_analysis"] += 1
            if len({r["side"] for r in mas}) > 1:
                cnt["r1_excluded_meta_analyses_disagree"] += 1
            else:
                y0 = min(r["year"] for r in mas)
                prim = [r for r in dated if r["dsg"] not in ("meta_analysis", "review") and r["year"] < y0]
                if len({r["group"] for r in prim}) >= 2:
                    r1.append({"link": key, "label": int(mas[0]["side"] == "for"), "records": prim})
                else:
                    cnt["r1_excluded_fewer_than_2_earlier_primary"] += 1
        for t in dated:
            if t["dsg"] not in ("rct", "meta_analysis"):
                continue
            prev = [r for r in dated if r["group"] != t["group"] and r["year"] < t["year"]]
            if len(prev) >= 2:
                r2.append({"link": key, "label": int(t["side"] == "for"), "records": prev, "target": t["rec"].record_id})
    return {"R1": r1, "R2": r2, "counts": dict(cnt)}


def auc(units_: list[dict], score) -> float | None:
    pos = [(score(u), 0) for u in units_ if u["label"] == 1]
    neg = [(score(u), 0) for u in units_ if u["label"] == 0]
    return round(tied_auc(pos, neg), 3) if pos and neg else None


def boot_ci(units_: list[dict], score, n: int = 2000, seed: int = 0) -> list[float]:
    by = defaultdict(list)
    for u in units_:
        by[u["link"]].append(u)
    keys, rnd, vals = list(by), random.Random(seed), []
    for _ in range(n):
        smp = [u for k in (rnd.choice(keys) for _ in keys) for u in by[k]]
        a = auc(smp, score)
        if a is not None:
            vals.append(a)
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3)]


def r3_auc() -> float:
    pos, neg = [], []
    for u in units():
        e = r32.evaluate(u["card"], u["cvs"], u["alts"], v35=True)
        v = -1.0 if e.gate != "pass" else e.chain_state
        (pos if u["label"] == 1 else neg).append((v, 0))
    return round(tied_auc(pos, neg), 3)


def step3() -> dict:
    out = {}
    for var in VARIANTS:
        with context_variant(var):
            rows = with_years(pool())
            refs = build_refs(rows)
            sc = lambda u: link_state(u["records"])
            r1, r2 = refs["R1"], refs["R2"]
            out[var] = {
                "records": len(rows), "counts": refs["counts"],
                "R1": {"links": len(r1), "label_for": sum(u["label"] for u in r1), "auc": auc(r1, sc),
                       "sign_agreement": round(sum((sc(u) > 0) == bool(u["label"]) for u in r1) / len(r1), 3) if r1 else None},
                "R2": {"targets": len(r2), "links": len({u["link"] for u in r2}), "label_for": sum(u["label"] for u in r2),
                       "auc": auc(r2, sc), "ci95": boot_ci(r2, sc),
                       "links_whose_targets_disagree": sum(1 for k in {u["link"] for u in r2}
                                                           if len({u["label"] for u in r2 if u["link"] == k}) > 1),
                       "earlier_records_median": sorted(len(u["records"]) for u in r2)[len(r2) // 2] if r2 else None},
                "R3": {"auc_chain_state": r3_auc()}}
    (CAL / "record_weight_step3.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str) + "\n")
    return out


_WF, _RW = r32.weight_factors, r32.record_weight
CANDIDATE = "design_grade3+comparison_2+context_2+effect_rate_up"
BLIND = re.compile(r"double[- ]blind|triple[- ]blind|placebo|sham|assessor[- ]blind|blinded assessor|blinded outcome")
OPEN = re.compile(r"open[- ]label|unblinded|non[- ]blinded|not blinded|single[- ]arm|no blinding")
SUBJ = re.compile(r"quality of life|\bqol\b|pain|fatigue|self[- ]report|questionnaire|perceived|mood|depress|anxiety|"
                  r"sleep quality|satisfaction|well[- ]?being|psqi|sf-36|\bvas\b")
_ABS: dict = {}


def blinding(rec) -> str:
    """blinded / open / none, from the PubMed title and abstract (spec step6_step7_definitions.words)."""
    m = re.fullmatch(r"PMID:(\d+)", rec.record_id or "")
    if not m:
        return "none"
    p = m.group(1)
    if p not in _ABS:
        from hyparena.tools import pubmed
        _ABS.update({k: (v.get("title", "") + " " + v.get("abstract", "")).lower() for k, v in pubmed.fetch([p]).items()})
    a = _ABS.get(p, "")
    return "blinded" if BLIND.search(a) else "open" if OPEN.search(a) else "none"


def subjective(rec, claim) -> bool:
    txt = " ".join([str(claim.qualifiers.get("measure", "")), claim.object.label, rec.quote]).lower()
    return bool(SUBJ.search(txt))


GRADE3 = {"rct": 1.0, "meta_analysis": 1.0, "non_randomised": 0.5, "observational": 0.5}


def weight_variant(rec, claim, against: bool, var: str) -> float:
    """The record weight under one variant of the menu (step4_factors); 'current' = v3.5."""
    f = _WF(rec, claim, against, v34=True)
    if not f:
        return 0.0
    v = {k: float(f[k][1]) for k in FACTORS}
    pre = claim.link in r3.PRECLINICAL_LINKS
    clinical_scale = r3.human_claim(claim) and not pre
    if against:
        v["precision"], v["effect"] = r32.null_power(rec.n_total, rec.comparison), 1.0
    for one in var.split("+"):                 # a combination is several menu items joined by "+"
        if one.startswith("drop_"):
            v[one[5:]] = 1.0
        elif one == "design_grade3" and clinical_scale:
            v["design"] = GRADE3.get(r3.record_design(rec), 0.25)
        elif one == "precision_steps3" and not against and not pre:
            n = rec.n_total
            v["precision"] = 0.25 if not n or n < 50 else 0.5 if n < 300 else 1.0
        elif one == "precision_power_both" and not against and not pre:
            large = v["effect"] >= 1.0
            v["precision"], v["effect"] = r32.null_power(rec.n_total, rec.comparison), 1.0
            v["precision"] = min(1.0, v["precision"] * (1.5 if large else 1.0))
        elif one == "effect_rate_up" and not against:
            v["effect"] = 0.5 if v["effect"] < 0.25 + 0.75 * 0.5 / 0.8 - 1e-9 else 1.0      # below "medium" (d < 0.5) -> 1/2
        elif one == "comparison_2":
            v["comparison"] = 1.0 if (rec.comparison == "between_groups") else 0.5
        elif one == "context_2":
            v["context"] = 0.5 if f["context"][0] == "adjacent" else 1.0
        elif one.startswith("rob_") and not pre and r3.record_design(rec) in ("rct", "non_randomised"):
            b = blinding(rec)
            if one == "rob_words3" and not against or one == "rob_words3_both_sides":
                v["rob"] = {"blinded": 1.0, "open": 0.5, "none": 2 / 3}[b]
            elif one == "rob_subjective" and not against and b != "blinded" and subjective(rec, claim):
                v["rob"] = 0.5
        elif one == "subgroup_only" and not against and "subgroup_only" in rec.flags:
            v["subgroup"] = 0.5
    return math.prod(v.values())


STEP4 = ("current", *(f"drop_{k}" for k in FACTORS), "design_grade3", "precision_steps3", "precision_power_both",
         "effect_rate_up", "comparison_2", "context_2")


@contextmanager
def weight_rule(var: str):
    r32.record_weight = lambda rec, claim, against, v34=False: (weight_variant(rec, claim, against, var)
                                                                 if r3.usable(rec, r32.VARIANT_BASE) else 0.0)
    try:
        yield
    finally:
        r32.record_weight = _RW


def paired_diff(units_: list[dict], s_new, s_old, n: int = 2000, seed: int = 1) -> list[float]:
    by = defaultdict(list)
    for u in units_:
        by[u["link"]].append(u)
    keys, rnd, vals = list(by), random.Random(seed), []
    for _ in range(n):
        smp = [u for k in (rnd.choice(keys) for _ in keys) for u in by[k]]
        a, b = auc(smp, s_new), auc(smp, s_old)
        if a is not None and b is not None:
            vals.append(a - b)
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3)]


FOLDS = ("beta_current", "loglr_sum", "best_evidence", "count_diff", "fold_rest_0", "fold_rest_1")
LAMBDA = 2 * math.atanh(2 / 3) / 0.6


def s_of(F: float, A: float, mode: str, c: float = r32.C_ANCHOR) -> float:
    if mode == "loglr_sum":
        return math.tanh(LAMBDA * (F - A) / 2)
    if mode == "best_evidence":
        return F if F > A else -A if A > F else 0.0
    if mode == "count_diff":
        return (F - A) / (F + A + 1)
    return 2 * (c * F + 1) / (c * (F + A) + 2) - 1


def link_state_mode(rows: list[dict], mode: str) -> float:
    side = {"for": defaultdict(list), "against": defaultdict(list)}
    for r in rows:
        side[r["side"]][r["group"]].append(r["w"])
    rest = {"fold_rest_0": 0.0, "fold_rest_1": 1.0}.get(mode, r32.FOLD_REST)
    if mode == "count_diff":
        F, A = len(side["for"]), len(side["against"])
    elif mode == "best_evidence":
        F, A = (max((max(ws) + rest * (sum(ws) - max(ws)) for ws in side[k].values()), default=0.0) for k in ("for", "against"))
    else:
        F, A = (sum(max(ws) + rest * (sum(ws) - max(ws)) for ws in side[k].values()) for k in ("for", "against"))
    return s_of(F, A, mode)


@contextmanager
def fold_rule(mode: str):
    """R3 under a fold: side_weight and strength of rules_v32 patched (the gate is computed by rules_v3, unchanged)."""
    sw, st, fr = r32.side_weight, r32.strength, r32.FOLD_REST
    if mode in ("fold_rest_0", "fold_rest_1"):
        r32.FOLD_REST = {"fold_rest_0": 0.0, "fold_rest_1": 1.0}[mode]
    if mode == "count_diff":
        r32.side_weight = lambda recs, claim, against, fold, v34=False: float(len(
            {r32.group_key(r) for r in recs if r32.record_weight(r, claim, against, v34) > 0}))
    if mode == "best_evidence":
        def best(recs, claim, against, fold, v34=False):
            g = defaultdict(list)
            for r in recs:
                g[r32.group_key(r)].append(r32.record_weight(r, claim, against, v34))
            return max((max(ws) + r32.FOLD_REST * (sum(ws) - max(ws)) for ws in g.values()), default=0.0)
        r32.side_weight = best
    if mode in ("loglr_sum", "best_evidence", "count_diff"):
        def strength(F, A, c=r32.C_ANCHOR):
            S = (1 + s_of(F, A, mode, c)) / 2
            return S, S, S
        r32.strength = strength
    try:
        yield
    finally:
        r32.side_weight, r32.strength, r32.FOLD_REST = sw, st, fr


STEP6 = (CANDIDATE, CANDIDATE + "+rob_words3", CANDIDATE + "+rob_words3_both_sides", CANDIDATE + "+rob_subjective",
         CANDIDATE + "+subgroup_only")


def step67() -> dict:
    out = {}
    for cv in VARIANTS:
        with context_variant(cv):
            rows = with_years(pool())
            refs = build_refs(rows)
            cnt = Counter((blinding(r["rec"]), subjective(r["rec"], r["claim_obj"])) for r in rows
                          if not r["pre"] and r3.record_design(r["rec"]) in ("rct", "non_randomised"))
            res = {"trial_records_blinding_x_subjective": {f"{b}|{'subjective' if s_ else 'objective'}": n for (b, s_), n in cnt.items()}}

            def scorer(var, mode="beta_current"):
                ws = {id(r): weight_variant(r["rec"], r["claim_obj"], r["side"] == "against", var) for r in rows}
                return lambda u: link_state_mode([{**r, "w": ws[id(r)]} for r in u["records"]], mode)
            cur = scorer("current")
            base = scorer(CANDIDATE)
            for var in ("current", *STEP6):
                f = scorer(var)
                with weight_rule(var):
                    r3a = r3_auc()
                res[var] = {"R2": auc(refs["R2"], f), "R1": auc(refs["R1"], f), "R3": r3a,
                            "dR2_vs_current": None if var == "current" else paired_diff(refs["R2"], f, cur),
                            "dR2_vs_candidate": None if var in ("current", CANDIDATE) else paired_diff(refs["R2"], f, base)}
            for mode in FOLDS[1:]:
                f = scorer(CANDIDATE, mode)
                with weight_rule(CANDIDATE), fold_rule(mode):
                    r3a = r3_auc()
                res["fold:" + mode] = {"R2": auc(refs["R2"], f), "R1": auc(refs["R1"], f), "R3": r3a,
                                       "dR2_vs_candidate": paired_diff(refs["R2"], f, base)}
            out[cv] = res
    (CAL / "record_weight_step67.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def step4(variants=STEP4) -> dict:
    out = {}
    for cv in VARIANTS:
        with context_variant(cv):
            rows = with_years(pool())
            refs = build_refs(rows)
            links = defaultdict(list)
            for r in rows:
                links[(r["unit"], r["claim"])].append(r)
            keys = sorted(links)
            score = {}
            for var in variants:                       # the weight of every record under the variant
                ws = {id(r): weight_variant(r["rec"], r["claim_obj"], r["side"] == "against", var) for r in rows}
                score[var] = lambda u, ws=ws: link_state([{**r, "w": ws[id(r)]} for r in u["records"]])
                score[var + "_links"] = [link_state([{**r, "w": ws[id(r)]} for r in links[k]]) for k in keys]
            res = {}
            for var in variants:
                with weight_rule(var):
                    r3a = r3_auc()
                res[var] = {"R2": auc(refs["R2"], score[var]), "R1": auc(refs["R1"], score[var]), "R3": r3a,
                            "R2_diff_ci95": None if var == "current" else paired_diff(refs["R2"], score[var], score["current"]),
                            "rho_links_vs_current": round(float(spearmanr(score[var + "_links"], score["current_links"]).statistic), 3)}
            out[cv] = res
    (CAL / "record_weight_step4.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


PACK5_DIR = CAL.parents[1] / "reviews" / "argon-2026-11-08"
PACK5_INSTRUCTIONS = """You are reviewing evidence the way an evidence-based-medicine reviewer would (GRADE-style judgement).

Each item is a CLAIM from a hypothesis about an intervention in older adults, and TWO PUBLISHED RECORDS (A and B) that a
reader found for that claim: PMID, title, abstract, the sentence the reader took as the finding (quote) and whether the
reader read it as evidence FOR or AGAINST the claim.

Part 1, pairs. For each pair decide which record is STRONGER EVIDENCE ABOUT THE CLAIM, whatever its direction: which one
should move a careful reviewer's belief in the claim more (up if it is for, down if it is against). Consider the study
design, its size, the comparison, the size of the effect, how directly it tests the claim's intervention, population and
outcome, and the risk of bias (blinding, placebo or sham, self-reported outcomes). Answer A, B or equal; equal when you
would not order them. Give a confidence 1 (unsure) to 3 (clear) and up to three reason codes, the first being the main one:
design, sample_size, effect_size, comparison, directness_intervention, directness_population, directness_outcome,
risk_of_bias, finding_misread, other. Use finding_misread when the reader's quote or its for / against reading is wrong.
Some pairs appear twice with A and B swapped; judge each item on its own.

Part 2, records. For each record id in `records`, label from the title and abstract:
- design: rct | non_randomised | observational | animal | cells | review | meta_analysis | other
- n_total: the number of participants (or animals) analysed, if the abstract states one number; else null
- context, relative to the claim it belongs to (see `claim_of_record`):
  exact = the intervention the claim names, in the claim's population (a claim that names a kind - "resistance training",
  "probiotics" - is matched exactly by any study of that kind); adjacent = the same intervention but another population,
  age, sex, species, dose or schedule, or another comparator than the claim fixes (only qualifiers the claim states count);
  class = the claim names a specific product, compound or programme and the study used another member of its kind;
  none = another intervention altogether, or no result on the claim
- blinding: double_blind | single_blind | assessor_blind | open | not_reported | not_applicable
- outcome_subjective: true when the outcome of the quote is self-reported or rated by the participant (quality of life,
  pain, fatigue, mood, sleep questionnaires), false for measured outcomes, null when unclear
- effect_phrase: the verbatim phrase giving the size of the effect (a ratio, a standardised difference, a percent or mean
  difference with its interval), or null

Answer with one JSON object, nothing else:
{"task": "pairs", "pairs": [{"id": "P01", "stronger": "A" | "B" | "equal", "confidence": 1 | 2 | 3, "reasons": ["design", ...],
  "note": "one sentence"}], "records": [{"id": "R001", "design": "...", "n_total": 120 | null, "context": "...",
  "blinding": "...", "outcome_subjective": true | false | null, "effect_phrase": "..." | null}]}
"""


def _logw(f: dict) -> dict:
    return {k: math.log(f[k][1]) for k in FACTORS}


@context_variant("verifier")      # as recorded in the spec (the verifier's context label)
def pack5() -> dict:
    """Pack 5 for Argon: pairs of records of one prospective link (spec references.R4_pairs_argon)."""
    from hyparena.tools import pubmed
    rows = [r for r in pool() if r["sample"] == "prospective"]
    links = defaultdict(list)
    for r in rows:
        links[(r["unit"], r["claim"])].append(r)
    cand = []
    for key, rs in links.items():
        for i, a in enumerate(rs):
            for b in rs[i + 1:]:
                if a["pmid"] == b["pmid"]:
                    continue
                la, lb = _logw(a), _logw(b)
                diff = {k: abs(la[k] - lb[k]) for k in FACTORS}
                dlw = abs(math.log(a["w"] / b["w"]))
                stratum = "near_tie" if dlw < 0.15 else max(diff, key=diff.get)
                cand.append({"key": key, "a": a, "b": b, "stratum": stratum, "dlogw": dlw,
                             "h": sha(f"pack5|{a['pmid']}|{b['pmid']}|{key}")})
    cand.sort(key=lambda c: c["h"])
    want = {**{k: 13 for k in FACTORS}, "near_tie": 15}
    picked, per_link = [], Counter()
    for c in cand:
        if want.get(c["stratum"], 0) > 0 and per_link[c["key"]] < 3:
            picked.append(c)
            want[c["stratum"]] -= 1
            per_link[c["key"]] += 1
    short = {k: v for k, v in want.items() if v > 0}
    for c in cand:                                   # fill the shortfall from the other strata
        if len(picked) >= 80:
            break
        if c not in picked and per_link[c["key"]] < 3:
            picked.append(c)
            per_link[c["key"]] += 1
    recs, rid = {}, {}
    for c in picked:
        for r in (c["a"], c["b"]):
            k = (r["pmid"], r["unit"], r["claim"], r["rec"].quote)
            if k not in rid:
                rid[k] = f"R{len(rid) + 1:03d}"
                recs[rid[k]] = r
    meta = pubmed.fetch(sorted({r["pmid"] for r in recs.values()}))
    claims, cid = {}, {}
    for c in picked:
        if c["key"] not in cid:
            cid[c["key"]] = f"C{len(cid) + 1:02d}"
            cl = c["a"]["claim_obj"]
            claims[cid[c["key"]]] = {"subject": cl.subject.label, "relation": cl.relation, "object": cl.object.label,
                                     "qualifiers": cl.qualifiers}
    items = []
    for i, c in enumerate(picked):
        items.append({"id": None, "claim": cid[c["key"]], "A": rid[(c["a"]["pmid"], c["a"]["unit"], c["a"]["claim"], c["a"]["rec"].quote)],
                      "B": rid[(c["b"]["pmid"], c["b"]["unit"], c["b"]["claim"], c["b"]["rec"].quote)], "src": i, "swapped": False})
    for i in range(15):
        x = items[i]
        items.append({**x, "A": x["B"], "B": x["A"], "swapped": True})
    items.sort(key=lambda x: sha(f"pack5-order|{x['src']}|{x['swapped']}"))
    for n, x in enumerate(items, 1):
        x["id"] = f"P{n:02d}"
    rec_of = {v: k for k, v in rid.items()}
    task = {"task": "pairs", "instructions": PACK5_INSTRUCTIONS, "claims": claims,
            "records": {i: {"pmid": r["pmid"], "title": meta.get(r["pmid"], {}).get("title", ""),
                            "abstract": meta.get(r["pmid"], {}).get("abstract", ""), "quote": r["rec"].quote,
                            "reader_reading": "for" if r["side"] == "for" else "against"} for i, r in sorted(recs.items())},
            "claim_of_record": {i: cid[(r["unit"], r["claim"])] for i, r in sorted(recs.items())},
            "pairs": [{"id": x["id"], "claim": x["claim"], "A": x["A"], "B": x["B"]} for x in items]}
    cw = lambda r: weight_variant(r["rec"], r["claim_obj"], r["side"] == "against", CANDIDATE + "+rob_subjective")
    key = {"pairs": [{"id": x["id"], "src": x["src"], "swapped": x["swapped"], "stratum": picked[x["src"]]["stratum"],
                      "link": list(picked[x["src"]]["key"]),
                      "w_v35": [round(recs[x["A"]]["w"], 4), round(recs[x["B"]]["w"], 4)],
                      "w_candidate": [round(cw(recs[x["A"]]), 4), round(cw(recs[x["B"]]), 4)]} for x in items],
           "records": {i: {"unit": r["unit"], "claim": r["claim"], "side": r["side"], "factors_v35": {k: r[k] for k in FACTORS},
                           "verifier_context": r["context"][0], "design": r["rec"].design, "n_total": r["rec"].n_total,
                           "blinding_words": blinding(r["rec"]), "subjective_rule": subjective(r["rec"], r["claim_obj"])}
                       for i, r in sorted(recs.items())},
           "strata_short": short}
    PACK5_DIR.mkdir(parents=True, exist_ok=True)
    (PACK5_DIR / "pack_5_task.json").write_text(json.dumps(task, indent=1, ensure_ascii=False) + "\n")
    (PACK5_DIR / "pack_5_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False, default=str) + "\n")
    return {"pairs": len(items), "unique_pairs": len(picked), "records": len(recs), "claims": len(claims),
            "strata": Counter(c["stratum"] for c in picked), "strata_short": short,
            "size_kb": round((PACK5_DIR / "pack_5_task.json").stat().st_size / 1024)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "step1"
    res = {"step1": step1, "step2-sample": lambda: f"{len(step2_sample())} records -> {CHECK}", "step2-score": step2_score,
           "step3": step3, "step4": step4, "step67": step67, "pack5": pack5}[cmd]()
    print(json.dumps(res, indent=1, ensure_ascii=False, default=str))

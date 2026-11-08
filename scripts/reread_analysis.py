"""Measures of the v11 re-read (specs/record-weight-2026-11-08.yaml, reread_v11). Free.

    python -m scripts.reread_analysis      # -> calibration/reread_v11_analysis.json
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict

from scipy.stats import kendalltau, spearmanr

from hyparena.backtest import tied_auc
from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification
from scripts.ablation import units
from scripts.pack6_analysis import wkappa
from scripts.v34_check import CAL, PROS, parts

ARGON = CAL.parents[1] / "reviews" / "argon-2026-11-08"


def reread(pool: str) -> dict[str, dict[str, ClaimVerification]]:
    p = (PROS if pool == "prospective" else CAL) / "reread_v11.json"
    out: dict = defaultdict(dict)
    for k, v in json.loads(p.read_text()).items():
        h, cid = k.split("|")
        out[h][cid] = ClaimVerification.model_validate(v)
    return out


def swap(cvs: list, new: dict) -> list:
    return [new.get(cv.id, cv) for cv in cvs]


def all_units(version: str) -> list[dict]:
    """Calibration units (with label) and prospective units (label None), with the v9 or the v11 chain records."""
    rc, rp = (reread("calibration"), reread("prospective")) if version == "v11" else ({}, {})
    out = [{**u, "cvs": swap(u["cvs"], rc.get(u["id"], {})), "sample": "calibration"} for u in units()]
    for h, r in json.loads((PROS / "run_60.json").read_text()).items():
        it = r["items"][0]
        if it.get("card") and it.get("verification") and "v3" in it:
            card, cvs, alts = parts(it, h)
            out.append({"id": h, "label": None, "card": card, "cvs": swap(cvs, rp.get(h, {})), "alts": alts, "sample": "prospective"})
    return out


def rows_of(us: list[dict], rob: bool = False) -> list[dict]:
    rows = []
    for u in us:
        claims = {c.id: c for c in u["card"].claims}
        for cv in u["cvs"]:
            cl = claims.get(cv.id)
            if cl is None:
                continue
            for side, recs in (("for", cv.evidence), ("against", cv.counterevidence)):
                for rec in recs:
                    w = r32.current_weight(rec, cl, side == "against")
                    if w <= 0:
                        continue
                    if rob and side == "for" and rob_hit(rec, cl):
                        w *= 0.5
                    m = rec.record_id.replace("PMID:", "")
                    rows.append({"unit": u["id"], "claim": cv.id, "side": side, "w": w, "rec": rec, "cl": cl, "pmid": m,
                                 "group": r32.group_key(rec), "sample": u["sample"]})
    return rows


def rob_hit(rec, cl) -> bool:
    return (cl.link not in r3.PRECLINICAL_LINKS and r3.record_design(rec) in ("rct", "non_randomised")
            and rec.blinding in ("open", "not_reported") and rec.outcome_subjective is True)


def r2_r3(us: list[dict], rob: bool = False) -> dict:
    import scripts.record_weight_check as m
    rows = rows_of(us, rob)
    from hyparena.tools import pubmed
    meta = pubmed.fetch(sorted({r["pmid"] for r in rows if r["pmid"].isdigit()}))
    for r in rows:
        y = (meta.get(r["pmid"], {}).get("year") or "")[:4]
        r["year"], r["dsg"] = (int(y) if y.isdigit() else None), r3.record_design(r["rec"])
    refs = m.build_refs(rows)
    f = lambda u: m.link_state_mode(u["records"], "loglr_sum")
    pos, neg = [], []
    rw = r32.record_weight
    if rob:
        r32.record_weight = lambda rec, cl, against, v34=False: rw(rec, cl, against, v34) * (0.5 if (not against and rob_hit(rec, cl)) else 1.0)
    try:
        for u in us:
            if u["label"] in (0, 1):
                e = r32.evaluate(u["card"], u["cvs"], u["alts"], v36=True)
                (pos if u["label"] == 1 else neg).append((-1.0 if e.gate != "pass" else e.chain_state, 0))
    finally:
        r32.record_weight = rw
    return {"R2": m.auc(refs["R2"], f), "R2_targets": len(refs["R2"]), "R3": round(tied_auc(pos, neg), 3)}


def labels(us9: list[dict], us11: list[dict]) -> dict:
    task = json.loads((ARGON / "pack_5_task.json").read_text())
    key = json.loads((ARGON / "pack_5_key.json").read_text())
    ans = {r["id"]: r for r in json.loads((ARGON / "pack_5_answer.json").read_text())["records"]}

    def index(us):
        idx = defaultdict(list)
        for r in rows_of([u for u in us if u["sample"] == "prospective"]):
            idx[(r["unit"], r["claim"], r["pmid"])].append(r)
        return idx
    i9, i11 = index(us9), index(us11)
    out = {}
    for name, idx in (("v9", i9), ("v11", i11)):
        ctx, bl, found = [], Counter(), 0
        for rid, kr in key["records"].items():
            rs = idx.get((kr["unit"], kr["claim"], task["records"][rid]["pmid"]))
            if not rs:
                continue
            found += 1
            c = r32.context_v34(rs[0]["rec"], rs[0]["cl"]) or "none"
            ctx.append((c, ans[rid]["context"]))
            if name == "v11" and kr["design"] in ("rct", "non_randomised"):
                bl[(rs[0]["rec"].blinding, ans[rid]["blinding"])] += 1
        n = len(ctx)
        po = sum(a == b for a, b in ctx) / n
        ca, cb = Counter(a for a, _ in ctx), Counter(b for _, b in ctx)
        pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n ** 2
        out[name] = {"records_matched": found, "context_kappa_with_argon": round((po - pe) / (1 - pe), 3), "agreement": round(po, 3),
                     "class_share": round(ca.get("class", 0) / n, 3)}
        if name == "v11":
            agree = sum(v for (a, b), v in bl.items() if a == b)
            out[name]["blinding_vs_argon"] = {"agree": agree, "of": sum(bl.values()), "table": {f"{a}->{b}": v for (a, b), v in bl.most_common()}}
    return out


def hand(us11: list[dict]) -> dict:
    xs = [json.loads(l) for l in (CAL / "record_weight_context_check.jsonl").read_text().splitlines() if l.strip()]
    idx = defaultdict(list)
    for r in rows_of(us11):
        idx[(r["unit"], r["claim"], r["pmid"])].append(r)
    pairs9, pairs11 = [], []
    for x in xs:
        rs = idx.get((x["unit"], x["claim_id"], x["pmid"]))
        pairs9.append((x["verifier"]["context"], x["hand"]["context"]))
        if rs:
            pairs11.append((r32.context_v34(rs[0]["rec"], rs[0]["cl"]) or "none", x["hand"]["context"]))

    def k(p):
        n = len(p)
        po = sum(a == b for a, b in p) / n
        ca, cb = Counter(a for a, _ in p), Counter(b for _, b in p)
        pe = sum(ca[q] * cb[q] for q in set(ca) | set(cb)) / n ** 2
        return {"n": n, "kappa": round((po - pe) / (1 - pe), 3), "agreement": round(po, 3)}
    return {"v9": k(pairs9), "v11": k(pairs11)}


def novelty(us9: list[dict], us11: list[dict]) -> dict:
    ans = {t["id"]: t["novelty"] for t in json.loads((ARGON / "pack_7_answer.json").read_text())["trials"]}
    LAD = {"new_context": 0, "translation": 1, "analog": 2, "new_combination": 3, "new_link": 4}
    out = {}
    for name, us in (("v9", us9), ("v11", us11)):
        pairs, nearer, farther, conf = [], 0, 0, Counter()
        for u in us:
            if u["sample"] != "prospective" or u["id"] not in ans:
                continue
            with r32.method():
                N = nv.novelty(u["card"], u["cvs"]) or "unknown"
            a = ans[u["id"]]
            conf[f"{N}->{a}"] += 1
            if N in LAD and a in LAD:
                pairs.append((LAD[N] / 4, LAD[a] / 4))
                nearer += LAD[a] < LAD[N]
                farther += LAD[a] > LAD[N]
        out[name] = {"weighted_kappa": wkappa(pairs, levels=tuple(i / 4 for i in range(5))), "levelled": len(pairs),
                     "argon_nearer": nearer, "argon_farther": farther, "confusion": dict(conf.most_common())}
    return out


def r4(us11: list[dict]) -> dict:
    task = json.loads((ARGON / "pack_5_task.json").read_text())
    key = json.loads((ARGON / "pack_5_key.json").read_text())
    ans = {p["id"]: p for p in json.loads((ARGON / "pack_5_answer.json").read_text())["pairs"]}
    idx = defaultdict(list)
    for r in rows_of([u for u in us11 if u["sample"] == "prospective"]):
        idx[(r["unit"], r["claim"], r["pmid"])].append(r)
    TP = {p["id"]: p for p in task["pairs"]}
    x, y = [], []
    for p in key["pairs"]:
        if p["swapped"]:
            continue
        t = TP[p["id"]]
        ra, rb = (idx.get((key["records"][t[s]]["unit"], key["records"][t[s]]["claim"], task["records"][t[s]]["pmid"])) for s in ("A", "B"))
        if not ra or not rb:
            continue
        d = math.log(ra[0]["w"] / rb[0]["w"])
        y.append(0 if abs(d) < 0.1 else (1 if d > 0 else -1))
        x.append({"A": 1, "B": -1, "equal": 0}[ans[p["id"]]["stronger"]])
    return {"pairs": len(x), "tau_b": round(float(kendalltau(x, y, variant="b").statistic), 3)}


def main() -> dict:
    us9, us11 = all_units("v9"), all_units("v11")
    out = {"references_v9": r2_r3(us9), "references_v11": r2_r3(us11), "references_v11_rob": r2_r3(us11, rob=True),
           "labels_pack5": labels(us9, us11), "hand_labels": hand(us11), "novelty_pack7": novelty(us9, us11), "R4_v11": r4(us11)}
    p9 = {u["id"]: r32.evaluate(u["card"], u["cvs"], u["alts"], v36=True).chain_state for u in us9 if u["sample"] == "prospective"}
    p11 = {u["id"]: r32.evaluate(u["card"], u["cvs"], u["alts"], v36=True).chain_state for u in us11 if u["sample"] == "prospective"}
    ks = sorted(p9)
    out["prospective_balance_spearman_v9_v11"] = round(float(spearmanr([p9[k] for k in ks], [p11[k] for k in ks]).statistic), 3)
    rows11 = rows_of(us11)
    tr = [r for r in rows11 if r3.record_design(r["rec"]) in ("rct", "non_randomised") and r["cl"].link not in r3.PRECLINICAL_LINKS]
    out["v11_trial_records"] = {"n": len(tr), "blinding": dict(Counter(r["rec"].blinding for r in tr)),
                                "subjective": dict(Counter(str(r["rec"].outcome_subjective) for r in tr)),
                                "rob_hits_for": sum(1 for r in tr if r["side"] == "for" and rob_hit(r["rec"], r["cl"])),
                                "context": dict(Counter(r32.context_v34(r["rec"], r["cl"]) for r in rows11))}
    (CAL / "reread_v11_analysis.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

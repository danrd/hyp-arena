"""The test model of a hypothesis (specs/test-model-2026-11-09.yaml): arms, prediction matrix, decision criteria, rigour.

    ALLOW_PAID=1 python -m scripts.test_model run --part dev|holdout|calibration [--version v1]
    python -m scripts.test_model score --part dev|holdout [--version v1]     # free
    python -m scripts.test_model review --part holdout                        # free: the 10 trials for the hand review
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter

from hyparena.card import rules_v32 as r32
from hyparena.card.models import Claim
from scripts.v34_check import CAL, PROS, parts

ARGON = CAL.parents[1] / "reviews" / "argon-2026-11-08"
CONFIG = "configs/v3-flash-n10.yaml"
CHECKLIST = [{"id": "k_expect", "text": "expectation, placebo response or unblinding explains the result"},
             {"id": "k_attention", "text": "attention, contact or supervision that comes with the intervention explains it"},
             {"id": "k_cointerv", "text": "a co-intervention or another component of the product or programme explains it"},
             {"id": "k_selection", "text": "selection, allocation or attrition explains it"},
             {"id": "k_measure", "text": "measurement, practice or assessor effects explain it"},
             {"id": "k_course", "text": "the natural course or regression to the mean explains it"}]
SIGNS = {"+", "0", "-"}
ITEMS = ("active_control", "mechanism_contrast", "blinded_assessment", "engagement_marker")


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9%]+", " ", (s or "").lower()).split())


def verbatim(phrase, text: str) -> bool:
    return bool(phrase) and len(_norm(phrase)) > 3 and _norm(phrase) in _norm(text)


def split() -> dict:
    ids = sorted(json.loads((ARGON / "pack_6_key.json").read_text()), key=lambda h: hashlib.sha1(f"testmodel|{h}".encode()).hexdigest())
    return {"dev": ids[:29], "holdout": ids[29:]}


def units(part: str):
    if part == "calibration":
        texts = {}
        for s in (1, 2, 3, 4, 5):
            for l in (CAL / f"texts_{s}.jsonl").read_text().splitlines():
                if l.strip():
                    d = json.loads(l)
                    texts[d["id"]] = d["text"]
        for s in (1, 2, 3, 4, 5):
            for h, r in json.loads((CAL / f"run_{s}_v10.json").read_text()).items():
                it = r["items"][0]
                if it.get("card") and it.get("verification") and "v3" in it and h in texts:
                    yield h, texts[h], parts(it, h)
        return
    texts = {json.loads(l)["id"]: json.loads(l)["text"] for l in (PROS / "texts_60.jsonl").read_text().splitlines() if l.strip()}
    run = json.loads((PROS / "run_60.json").read_text())
    for h in split()[part]:
        yield h, texts[h], parts(run[h]["items"][0], h)


def compute(v: dict, text: str, alt_ids: list[str]) -> dict:
    """Code rules: verbatim checks, d from the matrix, R, criteria."""
    arms = {a["id"]: a for a in v.get("arms") or [] if isinstance(a, dict) and verbatim(a.get("phrase"), text)}
    outs = {o["id"]: o for o in v.get("outcomes") or [] if isinstance(o, dict) and verbatim(o.get("phrase"), text)}
    comps = {}
    for c in v.get("comparisons") or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "arms" and c.get("first") in arms and c.get("second") in arms and c.get("outcome") in outs:
            comps[c["id"]] = c
        elif c.get("type") == "mediator":
            comps[c["id"]] = c
    rows = {m.get("row"): {k: s for k, s in (m.get("cells") or {}).items() if k in comps}
            for m in v.get("matrix") or [] if isinstance(m, dict)}
    H = rows.get("H", {})
    if "held_equal" in v:   # v2: a competitor's "0" against H's sign on arms counts only with a verbatim phrase that the factor is held equal
        held = {(x.get("row"), x.get("comparison")) for x in v.get("held_equal") or [] if isinstance(x, dict) and verbatim(x.get("phrase"), text)}
        for aid, cells in rows.items():
            if aid == "H":
                continue
            for k in list(cells):
                if cells[k] == "0" and H.get(k) in ("+", "-") and comps[k].get("type") == "arms" and (aid, k) not in held:
                    cells[k] = H[k]
    d = {}
    for aid in alt_ids + [k["id"] for k in CHECKLIST]:
        A = rows.get(aid, {})
        diff = [k for k in comps if H.get(k) in SIGNS and A.get(k) in SIGNS and H[k] != A[k]]
        d[aid] = 1.0 if any(comps[k].get("type") == "arms" for k in diff) else 0.5 if diff else 0.0
    rig = v.get("rigour") or {}
    items = {k: bool((rig.get(k) or {}).get("present")) and verbatim((rig.get(k) or {}).get("phrase"), text) for k in ITEMS}
    R = sum(items.values()) / len(ITEMS)
    prim = next((c for c in comps.values() if c.get("type") == "arms" and (outs.get(c["outcome"]) or {}).get("primary")), None)
    crit = {}
    if prim:
        h = H.get(prim["id"])
        others = {aid: rows.get(aid, {}).get(prim["id"]) for aid in alt_ids + [k["id"] for k in CHECKLIST]}
        crit = {"primary": f"{arms[prim['first']]['name']} vs {arms[prim['second']]['name']} on {outs[prim['outcome']]['name']}",
                "H_predicts": h,
                "if_as_H_predicts_falls": sorted(a for a, s in others.items() if s in SIGNS and s != h),
                "if_null_falls": sorted(a for a, s in others.items() if s in ("+", "-")),
                "not_tested_by_primary": sorted(a for a, s in others.items() if s not in SIGNS)}
    return {"arms": len(arms), "arms_given": len(v.get("arms") or []), "outcomes": len(outs), "outcomes_given": len(v.get("outcomes") or []),
            "comparisons": len(comps), "d": d, "rigour": items, "R": R, "criteria": crit, "add_arm": v.get("add_arm")}


def run(part: str, version: str) -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask
    from hyparena.card.pipeline import _client
    out_p = (CAL if part == "calibration" else PROS) / f"test_model_{part}_{version}.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    todo = [u for u in units(part) if u[0] not in done]
    client, _ = _client(CONFIG, False, len(todo) * 3 + 5)
    tin = tout = 0
    for h, text, (card, cvs, alts) in todo:
        al = [{"id": a.id, "claim": f"{a.subject.label} - {a.relation.replace('_', ' ')} - {a.object.label}", "rationale": a.rationale}
              for a in card.proposed_alternatives]
        log: list = []
        v, _ = ask(client, role="test_model", family="deepseek", template="test_model", version=version,
                   variables={"registry_text": text, "claim_plain": card.claim_plain, "chain": [c for c in card.claims if c.link],
                              "alternatives": al, "checklist": CHECKLIST},
                   validate=lambda x: [] if isinstance(x.get("matrix"), list) else ['a "matrix" list'], rounds=2, log=log)
        done[h] = {"raw": v, **compute(v or {}, text, [a["id"] for a in al])}
        tin += sum(int(x.get("tokens_in") or 0) for x in log)
        tout += sum(int(x.get("tokens_out") or 0) for x in log)
        out_p.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    return {"trials": len(done), "this_run": len(todo), "usd_offpeak": round(tin * 0.15e-6 + tout * 0.6e-6, 4)}


def score(part: str, version: str) -> dict:
    from scipy.stats import spearmanr
    from scripts.pack6_analysis import D, wkappa
    res = json.loads((PROS / f"test_model_{part}_{version}.json").read_text())
    ans = {t["id"]: t for t in json.loads((ARGON / "pack_6_answer.json").read_text())["trials"]}
    key = json.loads((ARGON / "pack_6_key.json").read_text())
    judged = json.loads((PROS / "judge_alternatives_v2.json").read_text())
    pm, pj, I = [], [], {k: [] for k in ("I_alt", "I_a", "I_b", "argon_informativeness", "I_argon_d")}
    for h, r in res.items():
        aa = {a["id"]: a for a in ans[h]["alternatives"]}
        s_m = s_g = 0.0
        for aid, ka in key[h]["alternatives"].items():
            if aid not in aa:
                continue
            gd = max(D[aa[aid]["d_positive"]], D[aa[aid]["d_negative"]])
            jd = judged.get(h, {}).get("d", {}).get(aid)
            pm.append((r["d"].get(aid, 0.0), gd))
            if jd:
                pj.append((max(D[jd["d_positive"]], D[jd["d_negative"]]), gd))
            s_m += ka["a_v36"] * r["d"].get(aid, 0.0)
            s_g += ka["a_v36"] * gd
        i_alt = min(1.0, s_m / 1.5)
        I["I_alt"].append(i_alt)
        I["I_a"].append(min(1.0, (s_m + 0.5 * r["R"]) / 1.5))
        I["I_b"].append(1 - (1 - i_alt) * (1 - r["R"] / 2))
        I["argon_informativeness"].append(ans[h]["informativeness"])
        I["I_argon_d"].append(min(1.0, s_g / 1.5))
    rho = lambda a, b: round(float(spearmanr(I[a], I[b]).statistic), 3)
    return {"trials": len(res), "kappa_d_matrix_vs_argon": wkappa(pm), "kappa_d_judge_vs_argon_same_trials": wkappa(pj),
            "d_matrix": dict(Counter(x for x, _ in pm)), "R": dict(Counter(r["R"] for r in res.values())),
            "rigour_items": {k: sum(r["rigour"][k] for r in res.values()) for k in ITEMS},
            "verbatim_arms": f"{sum(r['arms'] for r in res.values())}/{sum(r['arms_given'] for r in res.values())}",
            "verbatim_outcomes": f"{sum(r['outcomes'] for r in res.values())}/{sum(r['outcomes_given'] for r in res.values())}",
            "spearman_with_argon_informativeness": {k: rho(k, "argon_informativeness") for k in ("I_alt", "I_a", "I_b")},
            "spearman_with_I_from_argon_d": {k: rho(k, "I_argon_d") for k in ("I_alt", "I_a", "I_b")}}


def review(part: str, version: str) -> list:
    res = json.loads((PROS / f"test_model_{part}_{version}.json").read_text())
    ans = {t["id"]: t for t in json.loads((ARGON / "pack_6_answer.json").read_text())["trials"]}
    ids = sorted(res, key=lambda h: hashlib.sha1(f"review|{h}".encode()).hexdigest())[:10]
    return [{"id": h, "criteria": res[h]["criteria"], "d": res[h]["d"], "R": res[h]["R"], "add_arm": res[h]["add_arm"],
             "argon_best_change": ans[h]["best_change"]} for h in ids]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "score", "review"])
    ap.add_argument("--part", choices=["dev", "holdout", "calibration"], required=True)
    ap.add_argument("--version", default="v1")
    a = ap.parse_args()
    out = run(a.part, a.version) if a.cmd == "run" else score(a.part, a.version) if a.cmd == "score" else review(a.part, a.version)
    print(json.dumps(out, indent=1, ensure_ascii=False))

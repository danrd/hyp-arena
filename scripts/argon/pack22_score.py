"""Argon pack 22 scored (specs/alternatives/benchmark-alternatives-2026-11-14.yaml): our proposed alternatives (the confirming
runs of the filtered search with the current reader, run_*_n14x.json) and a plain-LLM baseline against Argon's gold.

    python -m scripts.argon.pack22_score literature                  # free: Argon's papers among our searches and records
    ALLOW_PAID=1 python -m scripts.argon.pack22_score match           # the judge (qwen) pairs ours / the baseline with Argon's
    ALLOW_PAID=1 python -m scripts.argon.pack22_score baseline        # the plain LLM (deepseek) lists alternatives
    python -m scripts.argon.pack22_score sample                       # free: 20 matched pairs for the check by hand
    python -m scripts.argon.pack22_score score                        # free: coverage, precision, design verdict, kinds
"""
from __future__ import annotations

import argparse
import glob
import json
import random
from collections import Counter

from scripts.common.v34_check import CAL

D = CAL.parents[1] / "reviews" / "argon-2026-11-14"
RUNS = "n14x"
CONFIG = "configs/judges-generation.yaml"
JUDGE, BASELINE = "qwen", "deepseek"          # the judge is not the family that proposed ours (deepseek)
ORDER = {"unchanged": 0, "weakened": 1, "eliminated": 2}


def _load():
    key = json.loads((D / "pack_22_key.json").read_text())
    ans = {a["id"]: a for a in json.loads((D / "pack_22_answer.json").read_text())["items"]}
    task = {t["id"]: t for t in json.loads((D / "pack_22_task.json").read_text())["items"]}
    runs = {}
    for f in glob.glob(str(CAL / f"run_*_{RUNS}.json")):
        runs.update(json.loads(open(f).read()))
    return key, ans, task, runs


def ours_of(run: dict) -> list[dict]:
    out = []
    for i, a in enumerate(run["items"][0]["card"].get("proposed_alternatives") or [], 1):
        out.append({"id": f"Y{i}", "src": a["id"], "text": f"{a['subject']['label']} — {a['relation'].replace('_', ' ')} — "
                    f"{a['object']['label']}: {a.get('rationale', '')}", "on_positive": a.get("on_positive"),
                    "on_negative": a.get("on_negative"), "kind": None})
    return out


def argon_of(item: dict) -> list[dict]:
    return [{"id": f"X{a['rank']}", "rank": a["rank"], "kind": a["kind"], "text": f"{a['statement']} Distinguishing part: {a['distinguishing_part']}",
             "on_positive": a.get("design_on_expected_result"), "on_negative": a.get("design_on_null_result")}
            for a in item["alternatives"]]


def literature() -> dict:
    key, ans, task, runs = _load()
    valid = {(p["id"], p["rank"], p["pmid"]) for p in json.loads((D / "pack_22_check.json").read_text())["papers"] if p["valid"]}
    res, hold = Counter(), Counter()
    for aid, k in key.items():
        r = runs.get(k["unit"])
        if not r:
            continue
        it = r["items"][0]
        alts = {a["id"] for a in it["card"].get("proposed_alternatives") or []}
        own, altp = set(), set()
        for c in r["calls"]:
            if c.get("kind") == "search" and c.get("claim"):
                (altp if c["claim"] in alts else own).update(c.get("pmids") or [])
        recs = {e["record_id"].replace("PMID:", "") for cv in it["verification"]["claims"] for e in cv.get("evidence", []) + cv.get("counterevidence", [])}
        recs |= {e["record_id"].replace("PMID:", "") for av in (it.get("v3_alternatives") or {}).values() for e in av.get("evidence", []) + av.get("counterevidence", [])}
        for a in ans[aid]["alternatives"]:
            if a["kind"] != "substantive" or a["rank"] > 3:
                continue
            for p in a.get("literature") or []:
                if (aid, a["rank"], p["pmid"]) not in valid:
                    continue
                for C in ((res, hold) if k["holdout"] else (res,)):
                    C["papers"] += 1
                    C["given_by_any_search"] += p["pmid"] in own | altp
                    C["given_by_the_claims_searches"] += p["pmid"] in own
                    C["added_by_the_alternatives_searches"] += p["pmid"] in altp - own
                    C["recorded"] += p["pmid"] in recs
    out = {"all": dict(res), "holdout": dict(hold)}
    out["budget_question"] = {"added_share": round(res["added_by_the_alternatives_searches"] / res["papers"], 3),
                              "rule": "keep the alternatives' own searches when they add at least 0.1"}
    (D / "pack_22_literature.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


def _client():
    from hyparena.pipeline import _client as c
    return c(CONFIG, False, 200)[0]


def match() -> dict:
    from hyparena.card.llm import ask
    key, ans, task, runs = _load()
    out_f = D / "pack_22_match.json"
    done = json.loads(out_f.read_text()) if out_f.exists() else {}
    base = json.loads((D / "pack_22_baseline.json").read_text()) if (D / "pack_22_baseline.json").exists() else {}
    client = _client()
    for aid, k in key.items():
        xs = argon_of(ans[aid])
        lists = {"ours": ours_of(runs[k["unit"]]) if k["unit"] in runs else []}
        if aid in base:
            lists["baseline"] = [{"id": f"Y{i}", "text": b["statement"]} for i, b in enumerate(base[aid], 1)]
        for name, ys in lists.items():
            kk = f"{aid}|{name}"
            if kk in done or not ys:
                continue
            ok = lambda v: [] if isinstance(v.get("pairs"), list) else ['a "pairs" list']
            v, _ = ask(client, role="alt_match", family=JUDGE, template="alt_match", version="v1",
                       variables={"trial": task[aid]["text"][:3000], "xs": xs, "ys": ys}, validate=ok, rounds=2)
            done[kk] = (v or {}).get("pairs") or []
            out_f.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    return {"matched_lists": len(done)}


def baseline() -> dict:
    from hyparena.card.llm import ask
    key, ans, task, runs = _load()
    out_f = D / "pack_22_baseline.json"
    done = json.loads(out_f.read_text()) if out_f.exists() else {}
    client = _client()
    for aid in key:
        if aid in done:
            continue
        ok = lambda v: [] if isinstance(v.get("alternatives"), list) and v["alternatives"] else ['an "alternatives" list']
        v, _ = ask(client, role="alt_baseline", family=BASELINE, template="alt_baseline", version="v1",
                   variables={"trial": task[aid]["text"], "as_of": task[aid]["T"]}, validate=ok, rounds=2)
        done[aid] = ((v or {}).get("alternatives") or [])[:5]
        out_f.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    return {"lists": len(done)}


def _pairs(name: str):
    key, ans, task, runs = _load()
    m = json.loads((D / "pack_22_match.json").read_text())
    base = json.loads((D / "pack_22_baseline.json").read_text()) if (D / "pack_22_baseline.json").exists() else {}
    for aid, k in key.items():
        xs = {x["id"]: x for x in argon_of(ans[aid])}
        if name == "ours":
            ys = {y["id"]: y for y in ours_of(runs[k["unit"]])} if k["unit"] in runs else {}
        else:
            ys = {f"Y{i}": {"id": f"Y{i}", "text": b["statement"], "kind": b.get("kind"), "on_positive": b.get("design_on_expected_result"),
                            "on_negative": b.get("design_on_null_result")} for i, b in enumerate(base.get(aid, []), 1)}
        seen_x, seen_y, pairs = set(), set(), []
        for p in m.get(f"{aid}|{name}", []):
            x, y = p.get("x"), p.get("y")
            if x in xs and y in ys and x not in seen_x and y not in seen_y:
                seen_x.add(x); seen_y.add(y); pairs.append((xs[x], ys[y], p.get("reason", "")))
        yield aid, k, xs, ys, pairs


def sample(n: int = 20) -> dict:
    rows = [{"trial": aid, "argon": x["text"], "ours": y["text"], "judge": why}
            for aid, k, xs, ys, pairs in _pairs("ours") for x, y, why in pairs]
    random.Random(20261115).shuffle(rows)
    (D / "pack_22_match_sample.json").write_text(json.dumps(rows[:n], indent=1, ensure_ascii=False) + "\n")
    return {"sampled": min(n, len(rows)), "of": len(rows)}


def _wkappa(pairs):
    from scripts.search.bench_search import _wkappa
    return _wkappa(pairs, k=3)


def score() -> dict:
    out = {}
    for name in ("ours", "baseline"):
        cov, cov_sub, cov_met, prec_n, prec_d = Counter(), Counter(), Counter(), 0, 0
        vp, vn, kinds_ours = [], [], Counter()
        argon_kinds = Counter()
        for aid, k, xs, ys, pairs in _pairs(name):
            top = [x for x in xs.values() if x["rank"] <= 3]
            hit = {x["id"] for x, _, _ in pairs}
            for x in top:
                cov["n"] += 1; cov["hit"] += x["id"] in hit
                C = cov_sub if x["kind"] == "substantive" else cov_met
                C["n"] += 1; C["hit"] += x["id"] in hit
                argon_kinds[x["kind"]] += 1
            prec_d += len(ys); prec_n += len({y["id"] for _, y, _ in pairs})
            for x, y, _ in pairs:
                if x.get("on_positive") in ORDER and y.get("on_positive") in ORDER:
                    vp.append((ORDER[y["on_positive"]], ORDER[x["on_positive"]]))
                if x.get("on_negative") in ORDER and y.get("on_negative") in ORDER:
                    vn.append((ORDER[y["on_negative"]], ORDER[x["on_negative"]]))
            for y in ys.values():
                if y.get("kind"):
                    kinds_ours[y["kind"]] += 1
        share = lambda C: round(C["hit"] / C["n"], 3) if C["n"] else None
        out[name] = {"coverage_rank_1_3": share(cov), "coverage_substantive": share(cov_sub), "coverage_methodological": share(cov_met),
                     "precision": round(prec_n / prec_d, 3) if prec_d else None, "design_on_expected_wkappa": _wkappa(vp),
                     "design_on_null_wkappa": _wkappa(vn), "verdict_pairs": len(vp), "argon_kinds_rank_1_3": dict(argon_kinds),
                     "kinds": dict(kinds_ours)}
    out["rule"] = "alternatives_ok: coverage of rank 1-3 >= 0.6 and design-verdict weighted kappa >= 0.4"
    (D / "pack_22_score.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["literature", "match", "baseline", "sample", "score"])
    a = ap.parse_args()
    fn = {"literature": literature, "match": match, "baseline": baseline, "sample": sample, "score": score}[a.cmd]
    print(json.dumps(fn(), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

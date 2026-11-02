"""Calibration of method v2 on registry hypotheses outside the benchmark, in growing steps (user decision 2026-11-02).

    python -m scripts.calibration pick --step 1                     # step 1: 30 CT.gov trials outside the benchmark, by intervention type
    CTGOV_BATCH=calib CTGOV_ALLOW_RETRO=1 python -m scripts.ctgov_outcomes plan       # their outcome documents (no model calls)
    CTGOV_BATCH=calib ALLOW_PAID=1 python -m scripts.ctgov_outcomes run               # labels (DeepSeek, quotes checked by code)
    python -m scripts.calibration units --step 1                    # 10 decisive CT.gov + 2 ISRCTN units, balanced, after the labels
    ALLOW_PAID=1 python -m scripts.calibration run --step 1         # method v2 (configs/v2-flash.yaml) on the units, saved per unit
    python -m scripts.calibration score --step 1                    # tied AUC, ties, outcomes; free, also after a rule change

Pool: CT.gov 2000-2022 "aging itself" trials with an outcome document that are not in the benchmark (almost all registered after
the primary completion date), and ISRCTN trials dropped by the strict condition rule (already labelled). Each unit is evaluated as
of min(registration, primary completion): the trial's own result papers are published after the primary completion, so they are
cut. Texts and labels stay in the private repository ($KG_DIR); nothing of this pool is in data/benchmark.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import yaml

from scripts.benchmark_run import build_texts
from scripts.ctgov_outcomes import KG

HS = KG / "hypothesis_sources"
CAL = HS / "calibration"
UNITS = Path(__file__).resolve().parents[1] / "data" / "benchmark" / "v2_units.json"
TYPES = ("drug/supplement", "other (exercise etc.)", "behavioral", "device")
PICK = {1: {"drug/supplement": 18, "other (exercise etc.)": 18, "behavioral": 18, "device": 6}}   # 30 gave 13 with a document
UNITS_PER_STEP = {1: {"ctgov_pos": 5, "ctgov_neg": 5,   # step 1: 5 + 4 after the manual check (2 labels set to not_applicable)
                       "isrctn": ["ISRCTN13364395", "ISRCTN87404878"]}}


def _h(x: str) -> str:
    return hashlib.sha1(x.encode()).hexdigest()


def _type(c: dict) -> str:
    t = {i.get("type") for i in c.get("interventions") or []}
    if t & {"DRUG", "DIETARY_SUPPLEMENT", "BIOLOGICAL"}:
        return "drug/supplement"
    if "BEHAVIORAL" in t:
        return "behavioral"
    if "DEVICE" in t:
        return "device"
    return "other (exercise etc.)"


def pool() -> list[dict]:
    bench = {u["id"] for u in json.loads(UNITS.read_text())["units"]}
    cands = yaml.safe_load((HS / "ctgov_candidates.yaml").read_text())["items"]
    labelled = {x["nct"] for x in yaml.safe_load((HS / "ctgov_outcomes.yaml").read_text())["items"]}
    has_doc = lambda c: bool(c.get("result_pmids_listed") or c.get("result_pmids_si") or c.get("results_posted"))
    return [c for c in cands if c["source_id"] not in labelled and c["source_id"] not in bench and has_doc(c)]


def pick(step: int) -> list[dict]:
    """Step k takes, per intervention type, the next trials in SHA-1 order of the id (fixed before any label is read)."""
    taken = set()
    for s in range(1, step):
        taken |= {c["source_id"] for c in yaml.safe_load((CAL / f"pick_{s}.yaml").read_text())["items"]}
    by_type = {t: sorted([c for c in pool() if _type(c) == t and c["source_id"] not in taken], key=lambda c: _h(c["source_id"])) for t in TYPES}
    out = [c for t, n in PICK[step].items() for c in by_type[t][:n]]
    CAL.mkdir(parents=True, exist_ok=True)
    (CAL / f"pick_{step}.yaml").write_text(yaml.safe_dump({"step": step, "items": out}, allow_unicode=True, width=200, sort_keys=False))
    batch = HS / "ctgov_candidates_calib.yaml"                         # the labelling script's batch file: all steps so far
    prev = yaml.safe_load(batch.read_text())["items"] if batch.exists() else []
    seen = {c["source_id"] for c in prev}
    batch.write_text(yaml.safe_dump({"selection": "calibration pool (scripts/calibration.py)", "n": len(prev) + len(out),
                                     "items": prev + [c for c in out if c["source_id"] not in seen]},
                                    allow_unicode=True, width=200, sort_keys=False))
    return out


def as_of(c: dict) -> str:
    pc = (c.get("primary_completion") or "")[:10]
    pc = pc + "-01" if len(pc) == 7 else pc
    return min(x for x in (c["written_on"], pc) if x)


def units(step: int) -> list[dict]:
    """Balanced decisive units of this step: CT.gov in SHA-1 order within label, then the named ISRCTN trials."""
    cfg = UNITS_PER_STEP[step]
    picked = {c["source_id"]: c for c in yaml.safe_load((CAL / f"pick_{step}.yaml").read_text())["items"]}
    labels = {x["nct"]: x for x in yaml.safe_load((HS / "ctgov_outcomes_calib.yaml").read_text())["items"] if x["nct"] in picked}
    dec = sorted([n for n, x in labels.items() if x["label"] in ("positive", "null", "negative")], key=_h)
    pos = [n for n in dec if labels[n]["label"] == "positive"][:cfg["ctgov_pos"]]
    neg = [n for n in dec if labels[n]["label"] != "positive"][:cfg["ctgov_neg"]]
    out = [{"id": n, "source": "ctgov", "written_on": as_of(picked[n]), "label": int(n in pos), "type": _type(picked[n])} for n in pos + neg]
    isr = yaml.safe_load((KG / "recheck" / "isrctn_outcomes_run1_discarded.yaml").read_text())
    isr = {x["nct"]: x for x in (isr.get("items", isr) if isinstance(isr, dict) else isr)}
    icand = {c["source_id"]: c for c in yaml.safe_load((HS / "isrctn_candidates.yaml").read_text())["items"]}
    for n in cfg["isrctn"]:
        c = icand[n]
        end = str(c.get("overall_end") or "")[:10]
        out.append({"id": n, "source": "isrctn", "written_on": min(x for x in (c["written_on"], end) if x),
                    "label": int(isr[n]["label"] == "positive"), "type": "isrctn"})
    (CAL / f"units_{step}.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"labels of step {step}: {Counter(x['label'] for x in labels.values())}; units {len(out)}: "
          f"{Counter((u['label'], u['type']) for u in out)}")
    return out


def run(step: int, config: str = "configs/v2-flash.yaml") -> None:
    from hyparena.card.pipeline import run as v2
    us = json.loads((CAL / f"units_{step}.json").read_text())
    texts = build_texts([{k: u[k] for k in ("id", "source", "written_on")} for u in us], CAL / f"texts_{step}.jsonl")
    out_p = CAL / f"run_{step}.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    for t in texts:
        if t["id"] in done:
            continue
        res = v2([t["text"]], writer="human_registry", config=config, as_of=t["as_of"], max_calls=60, verifiers=["deepseek"])
        done[t["id"]] = res
        out_p.write_text(json.dumps(done, ensure_ascii=False, default=str))
        x = res["items"][0]
        print(json.dumps({"id": t["id"], "outcome": x["outcome"], "claims": len((x["card"] or {}).get("claims", [])),
                          "calls": res["meta"]["calls"]}), flush=True)


def score(step: int, results: dict | None = None) -> dict:
    """Tied AUC of evidence_first (without late_start) with the benchmark's order: known result 3 > ranked 2 + score >
    not evaluated 1 > filtered 0. Also how many positive-negative pairs tie."""
    from hyparena.backtest import PRIMARY_DROP, bootstrap_tied_auc, tied_auc
    from hyparena.aspid import aggregate, load_profiles
    from hyparena.card import indicators as ind
    from dataclasses import replace
    us = {u["id"]: u for u in json.loads((CAL / f"units_{step}.json").read_text())}
    res = results or json.loads((CAL / f"run_{step}.json").read_text())
    any_res = next(iter(res.values()))
    specs = [sp for sp in ind.for_meta(any_res["meta"]) if sp.id not in PRIMARY_DROP]
    keep = {sp.id for sp in specs}
    prof = load_profiles()["evidence_first"]
    prof = replace(prof, tiers=[t for t in [t if isinstance(t, str) else [i for i in t if i in keep] for t in prof.tiers] if t])
    values = {h: {k: v for k, v in (r["items"][0].get("indicators") or {}).items() if k in keep}
              for h, r in res.items() if r["items"][0]["outcome"] == "ranked"}
    agg = aggregate(values, specs, prof, K=10000) if values else None
    base = {"known_result": 3.0, "ranked": 2.0, "filtered": 0.0}
    sc = {}
    for h, r in res.items():
        o = r["items"][0]["outcome"]
        sc[h] = (base.get(o, 1.0) + (agg.expected[h] if o == "ranked" else 0.0), agg.std[h] if o == "ranked" else 0.0)
    pos = [sc[h] for h in sc if us[h]["label"] == 1]
    neg = [sc[h] for h in sc if us[h]["label"] == 0]
    a = tied_auc(pos, neg)
    lo, hi = bootstrap_tied_auc(pos, neg)
    ties = sum(abs(p[0] - q[0]) <= 1.96 * ((p[1] ** 2 + q[1] ** 2) / 10000) ** 0.5 for p in pos for q in neg) / max(1, len(pos) * len(neg))
    out = {"n": len(sc), "pos": len(pos), "neg": len(neg), "tied_auc": round(a, 3), "ci95": [round(lo, 3), round(hi, 3)],
           "tied_pairs": round(ties, 2), "outcomes": dict(Counter(r["items"][0]["outcome"] for r in res.values())),
           "scores": {h: [us[h]["label"], res[h]["items"][0]["outcome"], round(sc[h][0], 3)] for h in sorted(sc, key=lambda h: -sc[h][0])}}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["pick", "units", "run", "score"])
    ap.add_argument("--step", type=int, default=1)
    a = ap.parse_args()
    if a.cmd == "pick":
        out = pick(a.step)
        print(len(out), Counter(_type(c) for c in out))
    elif a.cmd == "units":
        units(a.step)
    elif a.cmd == "run":
        if os.environ.get("ALLOW_PAID") != "1":
            raise SystemExit("paid: set ALLOW_PAID=1")
        run(a.step)
    else:
        print(json.dumps(score(a.step), indent=1))


if __name__ == "__main__":
    main()

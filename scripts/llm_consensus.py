"""Baseline from the Eternal Search Omega preprint (user decision 2026-11-07): ask models "will it be confirmed experimentally?"
for each calibration trial and compare with P. Paid (about 146 calls on two cheap families).

    ALLOW_PAID=1 python -m scripts.llm_consensus      # -> $KG_DIR/hypothesis_sources/calibration/llm_consensus.json
    ALLOW_PAID=1 python -m scripts.llm_consensus --prospective   # the 60 ongoing trials, answers frozen by a hash (no outcome yet)

Leakage: the models may know the published result of older trials. Each call also asks whether the model remembers the trial
or its result; AUC is reported overall, without the remembered ones, and by sample (fresh 2023-2026 vs older).
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

from hyparena.backtest import tied_auc
from hyparena.card.llm import ask
from scripts.ceiling import CAL

FAMILIES = ("google", "deepseek")
CONFIG = "configs/v3-flash-n10.yaml"


def problems(v: dict) -> list[str]:
    out = []
    if v.get("confirmed") not in ("yes", "no"):
        out.append('"confirmed" must be "yes" or "no"')
    try:
        p = float(v.get("probability"))
        if not 0 <= p <= 1:
            out.append('"probability" must be in 0-1')
    except (TypeError, ValueError):
        out.append('"probability" must be a number')
    if v.get("knows_result") not in ("yes", "no"):
        out.append('"knows_result" must be "yes" or "no"')
    return out


def units() -> list[dict]:
    out = []
    for s in (1, 2, 3, 4, 5):
        us = {u["id"]: u for u in json.loads((CAL / f"units_{s}.json").read_text())}
        for l in open(CAL / f"texts_{s}.jsonl"):
            d = json.loads(l)
            u = us.get(d["id"])
            if u and u.get("label") in (0, 1):
                out.append({"id": d["id"], "step": s, "set": u.get("set") or f"step{s}", "label": u["label"],
                            "as_of": d.get("as_of") or u.get("written_on"), "text": d["text"]})
    return out


def auc(pts):
    pos, neg = [(v, 0) for v, l in pts if l == 1], [(v, 0) for v, l in pts if l == 0]
    return (round(tied_auc(pos, neg), 3), len(pts)) if pos and neg else None


def main(fake: bool = False) -> dict:
    from hyparena.card.pipeline import _client
    out_f = CAL / "llm_consensus.json"
    done = json.loads(out_f.read_text()) if out_f.exists() else {}
    us = units()
    client, _ = _client(CONFIG, fake, len(us) * len(FAMILIES) * 2 + 10)

    def one(job):
        u, fam = job
        key = f"{u['id']}|{fam}"
        if key in done:
            return key, done[key]
        v, got = ask(client, role="predict_outcome", family=fam, template="predict_outcome", version="v1",
                     variables={"text": u["text"], "as_of": u["as_of"]}, validate=problems, rounds=2)
        return key, ({**v, "family": got} if v and not problems(v) else None)
    with ThreadPoolExecutor(4) as ex:
        for key, v in ex.map(one, [(u, f) for u in us for f in FAMILIES]):
            done[key] = v
    out_f.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    v34 = {r["id"]: r for r in json.loads((CAL / "v34_check.json").read_text())["rows"]}
    rows = []
    for u in us:
        vs = [done.get(f"{u['id']}|{f}") for f in FAMILIES]
        if any(v is None for v in vs):
            continue
        r = v34.get(u["id"], {})
        rows.append({"id": u["id"], "set": u["set"], "label": u["label"], "P34": r.get("P34") if r.get("gate") == "pass" else (-1.0 if r else None),
                     "N": r.get("N"), "prob": sum(float(v["probability"]) for v in vs) / len(vs),
                     "yes_all": float(all(v["confirmed"] == "yes" for v in vs)),
                     "knows": any(v["knows_result"] == "yes" for v in vs),
                     **{f"prob_{f}": float(v["probability"]) for f, v in zip(FAMILIES, vs)}})
    def block(rs):
        return {"n": len(rs), "positives": sum(r["label"] for r in rs),
                "P34": auc([(r["P34"], r["label"]) for r in rs if r["P34"] is not None]),
                "models_mean_probability": auc([(r["prob"], r["label"]) for r in rs]),
                "unanimous_yes": auc([(r["yes_all"], r["label"]) for r in rs]),
                **{f"prob_{f}": auc([(r[f"prob_{f}"], r["label"]) for r in rs]) for f in FAMILIES},
                "yes_all_share": round(sum(r["yes_all"] for r in rs) / len(rs), 3) if rs else None}
    fresh = [r for r in rows if r["set"] in ("fresh", "exp_2023")]
    summary = {"all": block(rows), "without_remembered": block([r for r in rows if not r["knows"]]),
               "fresh_2023_2026": block(fresh), "older": block([r for r in rows if r not in fresh]),
               "remembered": sum(r["knows"] for r in rows)}
    from scipy.stats import spearmanr
    LV = ("new_context", "translation", "analog", "new_combination", "new_link")
    pn = [(r["prob"], LV.index(r["N"])) for r in rows if r["N"] in LV]
    summary["rho_prob_vs_N"] = round(float(spearmanr(*zip(*pn)).statistic), 3) if len(pn) > 5 else None
    pp = [(r["prob"], r["P34"]) for r in rows if r["P34"] is not None and r["P34"] >= 0]
    summary["rho_prob_vs_P34"] = round(float(spearmanr(*zip(*pp)).statistic), 3) if len(pp) > 5 else None
    (CAL / "llm_consensus_summary.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False) + "\n")
    return summary


def prospective(n: int = 60) -> str:
    """Ask the same question for the ongoing trials of the prospective pool and freeze the answers (spec with SHA-256)."""
    import datetime as dt
    import hashlib
    import yaml
    from hyparena.card.pipeline import _client
    from scripts.prospective import OUT, SPECS
    texts = [json.loads(l) for l in open(OUT / f"texts_{n}.jsonl")]
    out_f = OUT / f"llm_consensus_{n}.json"
    done = json.loads(out_f.read_text()) if out_f.exists() else {}
    client, _ = _client(CONFIG, False, len(texts) * len(FAMILIES) * 2 + 10)

    def one(job):
        d, fam = job
        key = f"{d['id']}|{fam}"
        if key in done:
            return key, done[key]
        v, got = ask(client, role="predict_outcome", family=fam, template="predict_outcome", version="v1",
                     variables={"text": d["text"], "as_of": d["as_of"]}, validate=problems, rounds=2)
        return key, ({**v, "family": got} if v and not problems(v) else None)
    with ThreadPoolExecutor(4) as ex:
        for key, v in ex.map(one, [(d, f) for d in texts for f in FAMILIES]):
            done[key] = v
    body = (json.dumps(done, indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode()
    out_f.write_bytes(body)
    today = dt.date.today().isoformat()
    spec = SPECS / f"prospective-llm-consensus-{today}.yaml"
    spec.write_text(yaml.safe_dump({
        "id": spec.stem, "frozen_on": today,
        "what": f"answers of {', '.join(FAMILIES)} to 'will the hypothesis be confirmed?' (prompt predict_outcome/v1) for the {n} ongoing trials of the prospective pool, before any outcome exists (Eternal Search baseline, specs/llm-consensus-2026-11-07.yaml)",
        "answers_file": f"longevity-kg hypothesis_sources/prospective/llm_consensus_{n}.json", "answers_sha256": hashlib.sha256(body).hexdigest(),
        "answered": sum(1 for v in done.values() if v), "of": len(done),
        "test_when_outcomes_exist": "tied AUC of the models' mean probability and of unanimous yes, next to P (scores_60_v34.json) and to their combination; same outcome labels and rule as specs/prospective-2026-11-06.yaml",
    }, allow_unicode=True, sort_keys=False))
    return str(spec)


if __name__ == "__main__":
    import sys
    if "--prospective" in sys.argv:
        if os.environ.get("ALLOW_PAID") != "1":
            raise SystemExit("paid: set ALLOW_PAID=1")
        print(prospective())
        raise SystemExit(0)
    fake = "--fake" in sys.argv
    if not fake and os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    print(json.dumps(main(fake), indent=1, ensure_ascii=False))

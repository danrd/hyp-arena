"""The prospective pool: ongoing trials scored before their outcomes exist (the start of the living arena, method-v3.md section 10).

    python -m scripts.prospective pool                  # CT.gov: ongoing interventional trials on ageing itself, primary completion
                                                       # 2026-11-01 .. 2028-12-31 (no model calls)
    python -m scripts.prospective pick --n 60           # a subsample, balanced by intervention type, SHA-1 order (fixed before scoring)
    ALLOW_PAID=1 python -m scripts.prospective run      # method v3 (configs/v3-flash-n10.yaml) on the picked trials, as of today
    ALLOW_PAID=1 python -m scripts.prospective estimand # endpoint category by two families (specs/estimand-2026-11-06.yaml)
    python -m scripts.prospective score                 # v3.2 P with its interval, I, V, scope, ASPID profiles (no calls)
    python -m scripts.prospective freeze                # the scores and their SHA-256 into specs/prospective-<date>.yaml

Selection as in the benchmark (scripts/hypothesis_sources_ctgov.py: a condition equal to one of CONDITIONS), with the statuses of
ongoing trials. Each trial is scored as of the run date: no outcome exists yet, so no date cut or memory check is needed. Scores are
recorded with a hash before any result; the comparison with outcomes comes when the trials report (tied AUC, the reading of the
calibration). Data: $KG_DIR/hypothesis_sources/prospective/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import urllib.parse
from collections import Counter
from pathlib import Path

import yaml

from scripts.ctgov_outcomes import KG

OUT = KG / "hypothesis_sources" / "prospective"
SPECS = Path(__file__).resolve().parents[1] / "specs"
CONFIG = "configs/v3-flash-n10.yaml"
STATUSES = ("RECRUITING", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION")
WINDOW = ("2026-11-01", "2028-12-31")


def pool() -> dict:
    import scripts.hypothesis_sources_ctgov as h
    q = " OR ".join(f'"{c}"' for c in sorted(h.CONDITIONS))
    params = {"query.cond": q, "filter.overallStatus": ",".join(STATUSES), "aggFilters": "studyType:int", "pageSize": 200,
              "format": "json"}
    sts, tok = [], None
    while True:
        d = h._get(h.BASE + "?" + urllib.parse.urlencode(dict(params, **({"pageToken": tok} if tok else {}))))
        sts += d.get("studies", [])
        tok = d.get("nextPageToken")
        if not tok:
            break
    h.FIRST_FROM, h.FIRST_TO = "1990-01-01", "2100-12-31"
    out = []
    for st in sts:
        c = h.candidate(st)
        if c is None:
            continue
        ps = st["protocolSection"]["statusModule"]
        pc = (ps.get("primaryCompletionDateStruct") or {}).get("date", "")
        if WINDOW[0] <= pc[:10] <= WINDOW[1] or (len(pc) == 7 and WINDOW[0][:7] <= pc <= WINDOW[1][:7]):
            out.append({**c, "overall_status": ps.get("overallStatus"), "primary_completion": pc})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pool.yaml").write_text(yaml.safe_dump({"built_on": dt.date.today().isoformat(), "statuses": list(STATUSES),
                                                   "window": list(WINDOW), "n": len(out), "items": out},
                                                  allow_unicode=True, sort_keys=False))
    from scripts.calibration import _type
    return {"ongoing_on_ageing": len(sts), "in_window": len(out), "types": dict(Counter(_type(c) for c in out))}


def pick(n: int = 60) -> dict:
    from scripts.calibration import TYPES, _type
    items = yaml.safe_load((OUT / "pool.yaml").read_text())["items"]
    by = {t: sorted((c for c in items if _type(c) == t), key=lambda c: hashlib.sha1(c["source_id"].encode()).hexdigest()) for t in TYPES}
    out, k = [], 0
    while len(out) < n and any(by.values()):                # round robin over the types, SHA-1 order within each
        t = TYPES[k % len(TYPES)]
        if by[t]:
            out.append(by[t].pop(0))
        k += 1
    today = dt.date.today().isoformat()
    units = [{"id": c["source_id"], "source": "ctgov", "written_on": today, "type": _type(c),
              "primary_completion": c["primary_completion"]} for c in out]
    (OUT / f"units_{n}.json").write_text(json.dumps(units, indent=1) + "\n")
    return {"picked": len(units), "types": dict(Counter(u["type"] for u in units))}


def _units(n: int) -> list[dict]:
    return json.loads((OUT / f"units_{n}.json").read_text())


def run(n: int = 60) -> None:
    from hyparena.card.pipeline import run as v3
    from scripts.benchmark_run import build_texts
    us = _units(n)
    texts = build_texts([{k: u[k] for k in ("id", "source", "written_on")} for u in us], OUT / f"texts_{n}.jsonl")
    out_p, cards_p = OUT / f"run_{n}.json", OUT / "cards_v10.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    frozen = json.loads(cards_p.read_text()) if cards_p.exists() else {}
    for t in texts:
        if t["id"] in done:
            continue
        card = frozen.get(t["id"])
        try:
            res = v3([t["text"]], writer="human_registry", config=CONFIG, as_of=t["as_of"], max_calls=60, verifiers=["deepseek"],
                     cards=[card] if card else None)
        except Exception as e:
            print(json.dumps({"id": t["id"], "error": f"{type(e).__name__}: {str(e)[:200]}"}), flush=True)
            continue
        if not card and res["items"][0].get("card"):
            frozen[t["id"]] = res["items"][0]["card"]
            cards_p.write_text(json.dumps(frozen, ensure_ascii=False, indent=1))
        done[t["id"]] = res
        out_p.write_text(json.dumps(done, ensure_ascii=False, default=str))
        x = res["items"][0]
        print(json.dumps({"id": t["id"], "outcome": x["outcome"], "claims": len((x["card"] or {}).get("claims", [])),
                          "calls": res["meta"]["calls"]}), flush=True)


def estimand(n: int = 60) -> None:
    """The estimand extraction of scripts/estimand_check.py on the picked trials (two families)."""
    import scripts.estimand_check as ec
    texts = [json.loads(l) for l in open(OUT / f"texts_{n}.jsonl")]
    ec.OUT = OUT / f"estimand_{n}.json"
    ec.texts = lambda: texts
    ec.run()


def endpoint_clinical(n: int, h: str):
    """Agreed endpoint category of the two families, else None (unknown: drawn over its range)."""
    f = OUT / f"estimand_{n}.json"
    d = json.loads(f.read_text()) if f.exists() else {}
    v = {d.get(f"{h}|{fam}", {}).get("clean", {}).get("endpoint") for fam in ("google", "deepseek")}
    return v.pop() if len(v) == 1 and None not in v and "not_stated" not in v else None


def score(n: int = 60) -> dict:
    """Method v3.4 (specs/v34-frontier-2026-11-07.yaml) -> scores_{n}_v34.json; scores_{n}.json (v3.2, frozen by its hash in
    specs/prospective-2026-11-06.yaml) is never rewritten."""
    from hyparena.card import aspid_v3, rules_v32, v3_extra
    from hyparena.card import novelty_v34 as nv
    from hyparena.card.models import ClaimVerification, HypothesisCard
    res = json.loads((OUT / f"run_{n}.json").read_text())
    rows, ax = {}, {}
    for h, r in res.items():
        it = r["items"][0]
        if not it.get("card") or not it.get("verification") or "v3" not in it:
            rows[h] = {"outcome": it["outcome"]}
            continue
        card = HypothesisCard.model_validate(it["card"])
        claims = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
        alts = {k: ClaimVerification.model_validate(v) for k, v in (it.get("v3_alternatives") or {}).items()}
        e = rules_v32.evaluate(card, claims, alts, v35=True)
        ext = v3_extra.extras(card, claims, it["v3"], r["meta"].get("as_of") or "")
        ext["support_share"] = e.support_share
        ext["chain_state"] = e.chain_state
        ext["N"] = nv.novelty(card, claims, e)
        ext["leverage"], ext["W_potential"], _ = nv.leverage(card, claims, e)
        ext["endpoint_clinical"] = endpoint_clinical(n, h)
        from hyparena.card import trend_genetics as tg
        ext["trend_pubmed"] = tg.trend_pubmed(card, r["meta"].get("as_of") or dt.date.today().isoformat())[0]
        ext["ai_role"] = card.ai_role
        rows[h] = {"outcome": it["outcome"], "gate": e.gate, "P": e.P, "P_lo": e.P_lo, "P_hi": e.P_hi, "I": e.I, "V": e.V,
                   "scope": e.scope, "ai_role": card.ai_role, "endpoint_clinical": ext["endpoint_clinical"], "trend_pubmed": ext["trend_pubmed"], "links": len(e.links), "weakest": e.weakest,
                   "support_share": e.support_share, "chain_state": e.chain_state, "N": ext["N"], "leverage": ext["leverage"], "W_potential": ext["W_potential"],
                   "method": "v3.5"}
        ax[h] = ({"P": e.P, "scope": e.scope, "I": e.I, "headroom_I": e.headroom_I, "gate": e.gate}, ext)
    for prof in aspid_v3.load():
        agg = aspid_v3.rank(ax, prof, K=10000)
        for h in (agg.expected if agg else {}):
            rows[h][f"aspid_{prof}"] = round(agg.expected[h], 4)
    (OUT / f"scores_{n}_v34.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    return {"units": len(rows), "scored": sum(1 for r in rows.values() if "P" in r),
            "outcomes": dict(Counter(r["outcome"] for r in rows.values())),
            "ai_role": dict(Counter(r.get("ai_role") for r in rows.values() if "P" in r))}


def freeze(n: int = 60) -> str:
    f = OUT / f"scores_{n}.json"
    body = f.read_bytes()
    today = dt.date.today().isoformat()
    spec = SPECS / f"prospective-{today}.yaml"
    spec.write_text(yaml.safe_dump({
        "id": f"prospective-{today}", "frozen_on": today,
        "what": f"scores of {n} ongoing trials (scripts/prospective.py), before any outcome exists",
        "method": "v3 run (configs/v3-flash-n10.yaml: normalize_card/v10, verify_claim/v9) scored with rules_v32, fold=True (P with a 90% interval, I, V = P x I, scope) and the ASPID trial profiles",
        "scores_file": f"longevity-kg hypothesis_sources/prospective/scores_{n}.json", "scores_sha256": hashlib.sha256(body).hexdigest(),
        "test_when_outcomes_exist": "outcome labels by the benchmark's rules; P tied AUC with 95% CI; signal: AUC >= 0.60 and lower bound > 0.45; no signal: AUC < 0.55",
    }, allow_unicode=True, sort_keys=False))
    return str(spec)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["pool", "pick", "run", "estimand", "score", "freeze"])
    ap.add_argument("--n", type=int, default=60)
    a = ap.parse_args()
    if a.cmd in ("run", "estimand"):
        if os.environ.get("ALLOW_PAID") != "1":
            raise SystemExit("paid: set ALLOW_PAID=1")
        (run if a.cmd == "run" else estimand)(a.n)
        return
    out = pool() if a.cmd == "pool" else pick(a.n) if a.cmd == "pick" else score(a.n) if a.cmd == "score" else freeze(a.n)
    print(json.dumps(out, indent=1, ensure_ascii=False) if not isinstance(out, str) else out)


if __name__ == "__main__":
    main()

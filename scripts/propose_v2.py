"""Alternatives proposed with the registry text and a checklist of competitor kinds (propose_alternatives/v2), d judged by
judge_alternatives/v2 (specs/informativeness-check-2026-11-08.yaml, fix_d step2). Paid; holdout trials only.

    ALLOW_PAID=1 python -m scripts.propose_v2 run      # -> prospective/alternatives_v2_holdout.json
"""
from __future__ import annotations

import json
import os

from scripts.judge_alternatives import CONFIG, apply_rules, split
from scripts.v34_check import PROS, parts


def run() -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card import alternatives_v3 as av
    from hyparena.card.llm import ask
    from hyparena.card.pipeline import _client
    from hyparena.tools import pubmed
    run_ = json.loads((PROS / "run_60.json").read_text())
    texts = {json.loads(l)["id"]: json.loads(l)["text"] for l in (PROS / "texts_60.jsonl").read_text().splitlines() if l.strip()}
    out_p = PROS / "alternatives_v2_holdout.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    ids = [h for h in split()["holdout"] if h not in done]
    client, _ = _client(CONFIG, False, len(ids) * 6 + 5)
    for h in ids:
        r = run_[h]
        card, _, _ = parts(r["items"][0])
        as_of = r["meta"].get("as_of")
        pmids = [str(p).replace("PMID:", "") for p in r["items"][0]["verification"].get("searched_pmids", [])]
        abstracts = {p: a for p, a in pubmed.fetch(pmids).items() if a.get("abstract")}
        log: list = []
        alts = av.propose(client, "deepseek", card, abstracts, as_of, log=log, version="v2", registry_text=texts[h])
        rows = [{"id": a.id, "claim": f"{a.subject.label} - {a.relation.replace('_', ' ')} - {a.object.label}",
                 "rationale": a.rationale} for a in alts]
        jlog: list = []
        value, _ = ask(client, role="judge_alternatives", family="deepseek", template="judge_alternatives", version="v2",
                       variables={"registry_text": texts[h], "claim_plain": card.claim_plain, "alternatives": rows},
                       validate=lambda v: [] if isinstance(v.get("alternatives"), list) else ['an "alternatives" list'],
                       rounds=2, log=jlog)
        d = apply_rules(value, texts[h], [x["id"] for x in rows])
        done[h] = {"alternatives": [{**x, "support_pmids": a.support_pmids, **d.get(x["id"], {})} for x, a in zip(rows, alts)],
                   "tokens_in": sum(x.get("tokens_in", 0) or 0 for x in log + jlog),
                   "tokens_out": sum(x.get("tokens_out", 0) or 0 for x in log + jlog)}
        out_p.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    tin, tout = sum(v["tokens_in"] for v in done.values()), sum(v["tokens_out"] for v in done.values())
    return {"trials": len(done), "alternatives": sum(len(v["alternatives"]) for v in done.values()),
            "tokens_in": tin, "tokens_out": tout, "usd_offpeak": round(tin * 0.15e-6 + tout * 0.6e-6, 4)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

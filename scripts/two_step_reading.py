"""Two-step reading on the pack-9 links (specs/reading-gold-2026-11-08.yaml, two_step_test). Paid for `run`.

    ALLOW_PAID=1 python -m scripts.two_step_reading run    # -> prospective/two_step_reading.json
    python -m scripts.two_step_reading score
"""
from __future__ import annotations

import json
import os
import sys

from scripts.reader_v12 import ARGON, targets
from scripts.v34_check import CAL, PROS

OUT = PROS / "two_step_reading.json"


def run() -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask
    from hyparena.card.pipeline import _client
    from hyparena.tools import pubmed
    from scripts.reader_v12 import CONFIG
    v13 = json.loads((PROS / "reader_v12_dev_v13.json").read_text())
    client, _ = _client(CONFIG, False, 80)
    out, tin, tout = {}, 0, 0
    for k, h, as_of, card, cl, papers in targets("dev"):
        kept = [p for p, d in v13[k]["decision"].items() if d in ("yes", "unsure")]
        meta = pubmed.fetch(kept)
        inv = {}
        log: list = []
        for i in range(0, len(kept), 10):
            rows = [{"pmid": p, "title": meta[p].get("title", ""), "abstract": meta[p].get("abstract", "")} for p in kept[i:i + 10]]
            v, _ = ask(client, role="results_inventory", family="deepseek", template="results_inventory", version="v1",
                       variables={"papers": rows}, validate=lambda x: [] if isinstance(x.get("papers"), list) else ['a "papers" list'],
                       rounds=2, log=log)
            for e in (v or {}).get("papers") or []:
                if isinstance(e, dict):
                    inv[str(e.get("pmid", "")).replace("PMID:", "").strip()] = e
        rows = [{"pmid": p, "intervention": (inv.get(p) or {}).get("intervention", ""), "population": (inv.get(p) or {}).get("population", ""),
                 "results": [r for r in (inv.get(p) or {}).get("results") or [] if isinstance(r, dict)]} for p in kept]
        v, _ = ask(client, role="claim_match", family="deepseek", template="claim_match", version="v1",
                   variables={"claim": cl, "qualifiers": ", ".join(f"{a}: {b}" for a, b in cl.qualifiers.items() if b), "papers": rows},
                   validate=lambda x: [] if isinstance(x.get("papers"), list) else ['a "papers" list'], rounds=2, log=log)
        match = {str(e.get("pmid", "")).replace("PMID:", "").strip(): e for e in (v or {}).get("papers") or [] if isinstance(e, dict)}
        out[k] = {"kept": kept, "inventory": inv, "match": match}
        tin += sum(int(x.get("tokens_in") or 0) for x in log)
        tout += sum(int(x.get("tokens_out") or 0) for x in log)
        OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return {"links": len(out), "tokens_in": tin, "tokens_out": tout, "usd_offpeak": round(tin * 0.15e-6 + tout * 0.6e-6, 4)}


def score() -> dict:
    ans = {i["id"]: i for i in json.loads((ARGON / "pack_9_answer.json").read_text())["items"]}
    key = json.loads((ARGON / "pack_9_key.json").read_text())
    two = json.loads(OUT.read_text())
    v13 = json.loads((PROS / "reader_v12_dev_v13.json").read_text())
    res = {}
    for name in ("v13_per_paper", "two_step"):
        tp = fn = fp = ok = 0
        for iid, it in ans.items():
            k = f"{key[iid]['unit']}|{key[iid]['claim']}"
            if name == "two_step":
                f = {p: (e or {}).get("finding") for p, e in two[k]["match"].items()}
            else:
                f = v13[k]["answered"]
            for p in it["papers"]:
                mine = f.get(p["pmid"]) if f.get(p["pmid"]) in ("for", "against") else None
                if p["finding"] in ("for", "against"):
                    if mine:
                        tp += 1
                        ok += mine == p["finding"]
                    else:
                        fn += 1
                elif mine:
                    fp += 1
        res[name] = {"recall": f"{tp}/{tp + fn} = {tp / (tp + fn):.2f}", "precision": f"{tp}/{tp + fp} = {tp / max(1, tp + fp):.2f}",
                     "direction": f"{ok}/{tp}"}
    (CAL / "two_step_reading.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


if __name__ == "__main__":
    print(json.dumps(run() if (sys.argv[1:] or ["score"])[0] == "run" else score(), indent=1))

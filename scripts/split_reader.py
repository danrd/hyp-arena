"""Split reader (specs/reader-model-2026-11-08.yaml, split_reader): DeepSeek's records, Gemini re-labels only the intervention
match and the contradicted qualifiers, one short call per claim. Paid for `run`.

    ALLOW_PAID=1 python -m scripts.split_reader run      # -> prospective/split_reader.json
    python -m scripts.split_reader score                  # free
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

from hyparena.card import rules_v32 as r32
from scripts.reader_model import ARGON, sample
from scripts.reread_v11 import CONFIG, items
from scripts.v34_check import CAL, PROS

OUT = PROS / "split_reader.json"
QKEYS = ("species", "sex", "age_at_start", "dose", "comparator", "population")
IM = ("exact", "dose_differs", "regimen_differs", "related_compound", "class", "other_intervention")


def run() -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask
    from hyparena.card.pipeline import _client
    from hyparena.tools import pubmed
    want = set(sample())
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    client, _ = _client(CONFIG, False, len(want) * 3 + 5)
    tin = tout = 0
    for h, as_of, card, cvs, _ in items("prospective"):
        for cv in cvs:
            if (h, cv.id) not in want or f"{h}|{cv.id}" in done:
                continue
            cl = next(c for c in card.claims if c.id == cv.id)
            recs = [r for r in cv.evidence + cv.counterevidence]
            if not recs:
                continue
            meta = pubmed.fetch(sorted({r.record_id.replace("PMID:", "") for r in recs}))
            rows = [{"rid": f"r{i}", "pmid": r.record_id.replace("PMID:", ""), "quote": r.quote,
                     "title": meta.get(r.record_id.replace("PMID:", ""), {}).get("title", ""),
                     "abstract": meta.get(r.record_id.replace("PMID:", ""), {}).get("abstract", "")[:1200]} for i, r in enumerate(recs, 1)]
            log: list = []
            value, fam = ask(client, role="relabel_context", family="google", template="relabel_context", version="v1",
                             variables={"claim": cl, "qualifiers": ", ".join(f"{k}: {v}" for k, v in cl.qualifiers.items() if v),
                                        "records": rows},
                             validate=lambda v: [] if isinstance(v.get("records"), list) else ['a "records" list'], rounds=2, log=log)
            lab = {x.get("rid"): x for x in (value or {}).get("records") or [] if isinstance(x, dict)}
            done[f"{h}|{cv.id}"] = {"family": fam, "labels": {rows[i]["pmid"] + "|" + str(i): lab.get(rows[i]["rid"]) for i in range(len(rows))}}
            tin += sum(int(x.get("tokens_in") or 0) for x in log)
            tout += sum(int(x.get("tokens_out") or 0) for x in log)
            OUT.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    return {"claims": len(done), "tokens_in": tin, "tokens_out": tout, "usd_list_price": round(tin * 1.5e-6 + tout * 9e-6, 3)}


def relabel(rec, lab):
    """The record with Gemini's intervention match and qualifiers (only the claim-stated ones can be 'no')."""
    if not lab:
        return rec
    im = lab.get("intervention_match") if lab.get("intervention_match") in IM else rec.qualifiers_match.get("intervention_match", "exact")
    if im == "other_intervention":
        return None
    no = {k for k in (lab.get("no") or []) if k in QKEYS}
    qm = {k: ("no" if k in no else "yes") for k in QKEYS}
    qm["intervention_match"] = im
    return rec.model_copy(update={"qualifiers_match": qm})


def score() -> dict:
    key = json.loads((ARGON / "pack_5_key.json").read_text())
    task = json.loads((ARGON / "pack_5_task.json").read_text())
    ans = {r["id"]: r for r in json.loads((ARGON / "pack_5_answer.json").read_text())["records"]}
    split = json.loads(OUT.read_text())
    want = set(sample())
    run_ = {h: (card, cvs) for h, _, card, cvs, _ in items("prospective")}
    pairs_old, pairs_new, dropped = [], [], 0
    for rid, kr in key["records"].items():
        h, cid = kr["unit"], kr["claim"]
        if (h, cid) not in want or f"{h}|{cid}" not in split:
            continue
        card, cvs = run_[h]
        cv = next(c for c in cvs if c.id == cid)
        cl = next(c for c in card.claims if c.id == cid)
        recs = cv.evidence + cv.counterevidence
        pm = task["records"][rid]["pmid"]
        idx = next((i for i, r in enumerate(recs) if r.record_id == f"PMID:{pm}"), None)
        if idx is None:
            continue
        old = recs[idx]
        new = relabel(old, split[f"{h}|{cid}"]["labels"].get(f"{pm}|{idx}"))
        pairs_old.append((r32.context_v34(old, cl) or "none", ans[rid]["context"]))
        if new is None:
            dropped += 1
            pairs_new.append(("none", ans[rid]["context"]))
        else:
            pairs_new.append((r32.context_v34(new, cl) or "none", ans[rid]["context"]))

    def k(p):
        n = len(p)
        po = sum(a == b for a, b in p) / n
        ca, cb = Counter(a for a, _ in p), Counter(b for _, b in p)
        pe = sum(ca[q] * cb[q] for q in set(ca) | set(cb)) / n ** 2
        return {"n": n, "kappa": round((po - pe) / (1 - pe), 3), "agreement": round(po, 3), "class_share": round(ca.get("class", 0) / n, 3)}
    out = {"deepseek_labels": k(pairs_old), "split_reader_labels": k(pairs_new), "dropped_as_other_intervention": dropped}
    (CAL / "split_reader.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run() if (sys.argv[1:] or ["score"])[0] == "run" else score(), indent=1))

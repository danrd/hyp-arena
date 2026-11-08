"""Is a stronger reader model worth it? (specs/reader-model-2026-11-08.yaml). Paid for `run`.

    ALLOW_PAID=1 python -m scripts.reader_model run     # Gemini 3.5 Flash on 30 claims -> prospective/reader_gemini.json
    python -m scripts.reader_model score                 # free
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification
from scripts.reread_v11 import CONFIG, items
from scripts.v34_check import CAL, PROS

ARGON = CAL.parents[1] / "reviews" / "argon-2026-11-08"
OUT = PROS / "reader_gemini.json"


def sample() -> list[tuple[str, str]]:
    key = json.loads((ARGON / "pack_5_key.json").read_text())
    c = Counter((r["unit"], r["claim"]) for r in key["records"].values())
    cl = sorted([k for k, v in c.items() if v >= 2], key=lambda k: hashlib.sha1(f"reader|{k[0]}|{k[1]}".encode()).hexdigest())
    return cl[:30]


def run() -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card import rules_v3 as r3
    from hyparena.card.pipeline import _client
    from hyparena.card.verifier import verify_claim
    want = set(sample())
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    tasks = []
    for h, as_of, card, cvs, logs in items("prospective"):
        for cl in r3.chain(card):
            if (h, cl.id) in want and f"{h}|{cl.id}" not in done and logs.get(cl.id):
                tasks.append((f"{h}|{cl.id}", as_of, card, cl, logs[cl.id]))
    client, _ = _client(CONFIG, False, len(tasks) * 4 + 10)
    lock, tok = threading.Lock(), {"in": 0, "out": 0}

    def one(t):
        k, as_of, card, cl, pmids = t
        log: list = []
        cv = verify_claim(client, "google", frozenset(), cl, card, as_of, log=log, fallback="deepseek",
                          expert_pmids=[(p, "re-read of the same papers") for p in pmids], search="fixed", template_version="v9")
        with lock:
            done[k] = cv.model_dump()
            tok["in"] += sum(int(x.get("tokens_in") or 0) for x in log if x.get("family") == "google")
            tok["out"] += sum(int(x.get("tokens_out") or 0) for x in log if x.get("family") == "google")
            OUT.write_text(json.dumps(done, ensure_ascii=False) + "\n")
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, tasks))
    return {"claims": len(done), "tokens_in": tok["in"], "tokens_out": tok["out"],
            "usd_list_price": round(tok["in"] * 1.5e-6 + tok["out"] * 9e-6, 3)}


def score() -> dict:
    from scripts.reread_analysis import reread
    key = json.loads((ARGON / "pack_5_key.json").read_text())
    task = json.loads((ARGON / "pack_5_task.json").read_text())
    ans = {r["id"]: r for r in json.loads((ARGON / "pack_5_answer.json").read_text())["records"]}
    want = set(sample())
    run_ = {h: (card, cvs) for h, _, card, cvs, _ in items("prospective")}
    readers = {"deepseek_original": {f"{h}|{cv.id}": cv for h, (_, cvs) in run_.items() for cv in cvs},
               "deepseek_second": {f"{h}|{c}": cv for h, d in reread("prospective", "v9").items() for c, cv in d.items()},
               "gemini": {k: ClaimVerification.model_validate(v) for k, v in json.loads(OUT.read_text()).items()}}
    labelled = [(rid, kr) for rid, kr in key["records"].items() if (kr["unit"], kr["claim"]) in want]
    out = {"argon_labelled_records": len(labelled)}
    base_stance = {}
    for name, rd in readers.items():
        found, ctx, des, nn, stance = 0, [], [], [], {}
        for rid, kr in labelled:
            h, cid = kr["unit"], kr["claim"]
            cv = rd.get(f"{h}|{cid}")
            card = run_[h][0]
            cl = next((c for c in card.claims if c.id == cid), None)
            if cv is None or cl is None:
                continue
            pm = task["records"][rid]["pmid"]
            recs = [(s, r) for s, lst in (("for", cv.evidence), ("against", cv.counterevidence)) for r in lst
                    if r.record_id == f"PMID:{pm}" and r32.current_weight(r, cl, s == "against") > 0]
            if not recs:
                continue
            found += 1
            side, r = recs[0]
            ctx.append((r32.context_v34(r, cl) or "none", ans[rid]["context"]))
            des.append(r.design == ans[rid]["design"])
            nn.append(r.n_total == ans[rid]["n_total"])
            stance[rid] = side
        if name == "deepseek_original":
            base_stance = stance
        n = len(ctx)
        po = sum(a == b for a, b in ctx) / n
        ca, cb = Counter(a for a, _ in ctx), Counter(b for _, b in ctx)
        pe = sum(ca[q] * cb[q] for q in set(ca) | set(cb)) / n ** 2
        both = [r for r in stance if r in base_stance]
        out[name] = {"coverage": round(found / len(labelled), 3), "context_kappa": round((po - pe) / (1 - pe), 3),
                     "class_share": round(ca.get("class", 0) / n, 3), "design_agree": round(sum(des) / n, 3),
                     "n_agree": round(sum(nn) / n, 3),
                     "stance_agree_with_original": round(sum(stance[r] == base_stance[r] for r in both) / len(both), 3) if both else None}
    (CAL / "reader_model.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run() if (sys.argv[1:] or ["score"])[0] == "run" else score(), indent=1))

"""The declared chain claims read again with verify_claim/v11 on the same papers (specs/record-weight-2026-11-08.yaml,
reread_v11). Paid (DeepSeek V4.1 Flash through CometAPI).

    ALLOW_PAID=1 python -m scripts.reread_v11 run --pool calibration|prospective   # -> <pool>/reread_v11.json
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from scripts.v34_check import CAL, PROS, parts

CONFIG = "configs/v3-flash-n10.yaml"


def items(pool: str):
    """(unit id, as_of, card, cvs, {claim id: PMIDs of its search log}) for every scored unit of the pool."""
    files = [PROS / "run_60.json"] if pool == "prospective" else [CAL / f"run_{s}_v10.json" for s in (1, 2, 3, 4, 5)]
    for f in files:
        for h, r in json.loads(f.read_text()).items():
            it = r["items"][0]
            if not (it.get("card") and it.get("verification") and "v3" in it):
                continue
            card, cvs, _ = parts(it)
            logs = {}
            for c in r.get("calls", []):
                if c.get("kind") == "search":
                    logs[c.get("claim")] = c.get("pmids", [])          # the last search of a claim is the one read
            yield h, r["meta"].get("as_of"), card, cvs, logs


def run(pool: str, limit: int = 0) -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card import rules_v3 as r3
    from hyparena.card.pipeline import _client
    from hyparena.card.verifier import verify_claim
    out_p = (PROS if pool == "prospective" else CAL) / "reread_v11.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    tasks = []
    for h, as_of, card, cvs, logs in items(pool):
        for cl in r3.chain(card):
            key = f"{h}|{cl.id}"
            if key not in done and logs.get(cl.id):
                tasks.append((key, h, as_of, card, cl, logs[cl.id]))
    tasks = tasks[:limit] if limit else tasks
    client, _ = _client(CONFIG, False, len(tasks) * 4 + 10)
    lock = threading.Lock()
    tokens = {"in": 0, "out": 0}

    def one(t):
        key, h, as_of, card, cl, pmids = t
        log: list = []
        cv = verify_claim(client, "deepseek", frozenset({"google"}), cl, card, as_of, log=log, fallback="google",
                          expert_pmids=[(p, "re-read of the same papers") for p in pmids], search="fixed",
                          template_version="v11")
        with lock:
            done[key] = cv.model_dump()
            tokens["in"] += sum(int(x.get("tokens_in") or 0) for x in log)
            tokens["out"] += sum(int(x.get("tokens_out") or 0) for x in log)
            out_p.write_text(json.dumps(done, ensure_ascii=False) + "\n")
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, tasks))
    return {"pool": pool, "claims_done": len(done), "this_run": len(tasks), "tokens_in": tokens["in"], "tokens_out": tokens["out"],
            "usd_offpeak_deepseek": round(tokens["in"] * 0.15e-6 + tokens["out"] * 0.6e-6, 3)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--pool", choices=["calibration", "prospective"], required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    print(json.dumps(run(a.pool, a.limit), indent=1))

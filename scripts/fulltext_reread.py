"""Full-text re-read of 'for' RCT records on the outcome link (specs/abstract-overstates-2026-11-09.yaml, fulltext_reread).

    ALLOW_PAID=1 python -m scripts.fulltext_reread run      # -> <pool>/fulltext_reread.json
    python -m scripts.fulltext_reread score                  # free
"""
from __future__ import annotations

import json
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification
from scripts.reread_v11 import CONFIG, items
from scripts.v34_check import CAL, PROS

ARGON = CAL.parents[1] / "reviews" / "argon-2026-11-08"


def targets(pool: str) -> list[tuple]:
    from hyparena.tools import pmc
    out, seen = [], {}
    for h, as_of, card, cvs, logs in items(pool):
        cl = {x.id: x for x in card.claims}
        for cv in cvs:
            k = cl.get(cv.id)
            if not k or k.link in r3.PRECLINICAL_LINKS:
                continue
            for r in cv.evidence:
                if r3.record_design(r) != "rct" or r32.current_weight(r, k, False) <= 0:
                    continue
                p = r.record_id.replace("PMID:", "")
                if p not in seen:
                    pc = pmc.pmcid(p)
                    seen[p] = bool(pc and pmc.is_open(pc))
                if seen[p]:
                    out.append((f"{h}|{cv.id}|{p}", h, as_of, card, k, p))
    return list({t[0]: t for t in out}.values())


def run() -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.pipeline import _client
    from hyparena.card.verifier import verify_claim
    res = {}
    for pool in ("prospective", "calibration"):
        out_p = (PROS if pool == "prospective" else CAL) / "fulltext_reread.json"
        done = json.loads(out_p.read_text()) if out_p.exists() else {}
        tasks = [t for t in targets(pool) if t[0] not in done]
        client, _ = _client(CONFIG, False, len(tasks) * 3 + 10)
        lock, tok = threading.Lock(), Counter()

        def one(t):
            key, h, as_of, card, k, p = t
            log: list = []
            cv = verify_claim(client, "deepseek", frozenset({"google"}), k, card, as_of, log=log, fallback="google",
                              expert_pmids=[(p, "full-text re-read")], search="fixed+fulltext", template_version="v13",
                              check_subgroups=False)
            with lock:
                done[key] = cv.model_dump()
                for x in log:
                    tok["in"] += int(x.get("tokens_in") or 0)
                    tok["out"] += int(x.get("tokens_out") or 0)
                out_p.write_text(json.dumps(done, ensure_ascii=False) + "\n")
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(one, tasks))
        res[pool] = {"records": len(done), "this_run": len(tasks), "usd_offpeak": round(tok["in"] * 0.15e-6 + tok["out"] * 0.6e-6, 4)}
    return res


def stance_of(cv: dict, p: str) -> str:
    c = ClaimVerification.model_validate(cv)
    if any(r.record_id == f"PMID:{p}" for r in c.counterevidence):
        return "against"
    if any(r.record_id == f"PMID:{p}" for r in c.evidence):
        return "for"
    return "none"


def replaced(pool: str) -> dict:
    """{unit: {claim: ClaimVerification}} with the full-text reading replacing the paper's records."""
    p_ = (PROS if pool == "prospective" else CAL) / "fulltext_reread.json"
    ft = json.loads(p_.read_text()) if p_.exists() else {}
    out: dict = {}
    for h, as_of, card, cvs, logs in items(pool):
        by = {cv.id: cv for cv in cvs}
        for key, v in ft.items():
            u, cid, p = key.split("|")
            if u != h or cid not in by:
                continue
            cv = out.setdefault(h, {}).get(cid) or by[cid]
            new = ClaimVerification.model_validate(v)
            rid = f"PMID:{p}"
            cv = cv.model_copy(update={"evidence": [r for r in cv.evidence if r.record_id != rid] + [r for r in new.evidence if r.record_id == rid],
                                       "counterevidence": [r for r in cv.counterevidence if r.record_id != rid] + [r for r in new.counterevidence if r.record_id == rid]})
            out.setdefault(h, {})[cid] = cv
    return out


def score() -> dict:
    out = {}
    flips = []
    for pool in ("prospective", "calibration"):
        p_ = (PROS if pool == "prospective" else CAL) / "fulltext_reread.json"
        ft = json.loads(p_.read_text()) if p_.exists() else {}
        c = Counter(stance_of(v, k.split("|")[2]) for k, v in ft.items())
        out[pool] = {"records": len(ft), "new_stance": dict(c)}
        flips += [k.split("|")[2] for k, v in ft.items() if stance_of(v, k.split("|")[2]) != "for"]
    known = ["38911477", "31121926", "29227175", "40011687", "36316421", "39764482"]
    out["known_cases"] = {p: (p in flips) for p in known}
    # references with the replaced records
    from scripts.reread_analysis import r2_r3
    from scripts.ablation import units
    import scripts.reread_analysis as ra
    rp, rc = replaced("prospective"), replaced("calibration")
    us = [{**u, "cvs": [rc.get(u["id"], {}).get(cv.id, cv) for cv in u["cvs"]], "sample": "calibration"} for u in units()]
    from scripts.v34_check import parts
    for h, r in json.loads((PROS / "run_60.json").read_text()).items():
        it = r["items"][0]
        if it.get("card") and it.get("verification") and "v3" in it:
            card, cvs, alts = parts(it, h)
            us.append({"id": h, "label": None, "card": card, "cvs": [rp.get(h, {}).get(cv.id, cv) for cv in cvs], "alts": alts, "sample": "prospective"})
    out["references_with_fulltext"] = r2_r3(us)
    out["references_before"] = r2_r3(ra.all_units("v9"))
    (CAL / "fulltext_reread_score.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run() if (sys.argv[1:] or ["score"])[0] == "run" else score(), indent=1))

"""Claim vs results table (specs/abstract-overstates-2026-11-09.yaml, claim_vs_results): one narrow question per 'for' RCT
record on the outcome link with an open paper, from the Results sections and tables; a 'no' or 'not_measured' counts only
with a verbatim quote and the agreement of a second model family.

    ALLOW_PAID=1 python -m scripts.claim_results run     # -> <pool>/claim_results.json
    python -m scripts.claim_results score                 # free
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

from hyparena.card.models import ClaimVerification
from scripts.fulltext_reread import ARGON, targets
from scripts.reread_v11 import CONFIG, items
from scripts.v34_check import CAL, PROS

CHANGE = ("no", "not_measured")
KNOWN_IN_SAMPLE = ["29227175", "40011687", "36316421", "39764482"]
STOP_USD = float(os.environ.get("STOP_USD", "0.15"))
VERSION = os.environ.get("CVR_VERSION", "v2")      # v1: the first 35 records; v2 adds outcomes_quote
SECOND = os.environ.get("CVR_SECOND", "0") == "1"   # user choice 2026-11-09 (variant V): no second model, Argon checks the changes


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9%.<>=]+", " ", (s or "").lower()).split())


def verbatim(q, text: str) -> bool:
    return bool(q) and len(_norm(q)) > 10 and _norm(q) in _norm(text)


def _ask(client, family, k, p, meta, res, log):
    from hyparena.card.llm import ask
    v, _ = ask(client, role="claim_vs_results", family=family, template="claim_vs_results", version=VERSION,
               variables={"claim": k, "qualifiers": ", ".join(f"{a}: {b}" for a, b in k.qualifiers.items() if b), "pmid": p,
                          "title": meta.get("title", ""), "abstract": meta.get("abstract", ""), "results": res},
               validate=lambda x: [] if x.get("y_between_groups") in ("yes", "no", "not_measured", "unclear") else ['"y_between_groups"'],
               rounds=2, log=log)
    return v or {}


def run() -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.pipeline import _client
    from hyparena.tools import pmc, pubmed
    out = {}
    usd = 0.0
    price = {"deepseek": (0.15e-6, 0.6e-6), "google": (1.5e-6, 9e-6)}
    for pool in ("prospective", "calibration"):
        out_p = (PROS if pool == "prospective" else CAL) / "claim_results.json"
        done = json.loads(out_p.read_text()) if out_p.exists() else {}
        todo = [t for t in targets(pool) if t[0] not in done]
        client, _ = _client(CONFIG, False, len(todo) * 6 + 10)
        for key, h, as_of, card, k, p in todo:
            if usd > STOP_USD:
                break
            meta = pubmed.fetch([p]).get(p, {})
            res = pmc.results_excerpt(p) or ""
            log: list = []
            a = _ask(client, "deepseek", k, p, meta, res, log)
            rec = {"version": VERSION, "first": a, "first_verbatim": verbatim(a.get("quote"), res), "results_chars": len(res),
                   "outcomes_verbatim": verbatim(a.get("outcomes_quote"), res + "\n" + meta.get("abstract", ""))}
            if SECOND and a.get("y_between_groups") in CHANGE and (rec["first_verbatim"] or a.get("y_between_groups") == "not_measured"):
                b = _ask(client, "google", k, p, meta, res, log)
                rec["second"] = b
                rec["second_verbatim"] = verbatim(b.get("quote"), res)
            for x in log:
                pi, po = price.get(x.get("family") or "deepseek", price["deepseek"])
                usd += int(x.get("tokens_in") or 0) * pi + int(x.get("tokens_out") or 0) * po
            done[key] = rec
            out_p.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
        out[pool] = {"records": len(done), "this_run": len(todo)}
    out["usd_offpeak"] = round(usd, 4)
    return out


def verdict(r: dict) -> str:
    """'for' (unchanged) | 'null' (moved to against, weighed by power) | 'drop' (removed from the link)."""
    """Variant V (user 2026-11-09): the first reading alone, checked by code; the changes go to Argon.
    'no' with a verbatim results quote -> null; 'not_measured' with a verbatim quote listing the measured outcomes -> drop."""
    a = r.get("first") or {}
    y = a.get("y_between_groups")
    if y == "no" and r.get("first_verbatim"):
        return "null"
    if y == "not_measured" and r.get("outcomes_verbatim"):
        return "drop"
    return "for"


def replaced(pool: str) -> dict:
    p_ = (PROS if pool == "prospective" else CAL) / "claim_results.json"
    cr = json.loads(p_.read_text()) if p_.exists() else {}
    out: dict = {}
    for h, as_of, card, cvs, logs in items(pool):
        by = {cv.id: cv for cv in cvs}
        for key, r in cr.items():
            u, cid, p = key.split("|")
            v = verdict(r)
            if u != h or cid not in by or v == "for":
                continue
            cv = out.setdefault(h, {}).get(cid) or by[cid]
            rid = f"PMID:{p}"
            moved = [x for x in cv.evidence if x.record_id == rid]
            cv = cv.model_copy(update={"evidence": [x for x in cv.evidence if x.record_id != rid],
                                       "counterevidence": cv.counterevidence + (moved if v == "null" else [])})
            out[h][cid] = cv
    return out


def score() -> dict:
    out, verdicts = {}, {}
    for pool in ("prospective", "calibration"):
        p_ = (PROS if pool == "prospective" else CAL) / "claim_results.json"
        cr = json.loads(p_.read_text()) if p_.exists() else {}
        verdicts.update({k: verdict(r) for k, r in cr.items()})
        out[pool] = {"records": len(cr), "first": dict(Counter((r.get("first") or {}).get("y_between_groups") for r in cr.values())),
                     "first_verbatim": sum(bool(r.get("first_verbatim")) for r in cr.values()),
                     "second_asked": sum("second" in r for r in cr.values()),
                     "verdict": dict(Counter(verdict(r) for r in cr.values())),
                     "results_empty": sum(r.get("results_chars", 0) == 0 for r in cr.values())}
    out["known_cases"] = {p: sorted({f"{k.split('|')[1]}: {v}" for k, v in verdicts.items() if k.endswith("|" + p)}) or "not in sample"
                          for p in KNOWN_IN_SAMPLE}
    out["proposed_not_counted"] = sum(1 for p_ in (PROS, CAL) if (p_ / "claim_results.json").exists()
                                      for r in json.loads((p_ / "claim_results.json").read_text()).values()
                                      if (r.get("first") or {}).get("y_between_groups") in CHANGE and verdict(r) == "for")
    a = json.loads((ARGON / "pack_11_answer.json").read_text())["items"]
    key = json.loads((ARGON / "pack_11_key.json").read_text())
    c = Counter()
    for it in a:
        kk = key[it["id"]]
        k2 = f"{kk['unit']}|{kk['claim']}|{kk['pmid']}"
        if k2 in verdicts and it["B"].get("status") == "read":
            ours = {"for": "for", "null": "against", "drop": "none"}[verdicts[k2]]
            c[(it["B"].get("finding"), ours)] += 1
    out["vs_pack11"] = {"same": sum(n for (x, y), n in c.items() if x == y), "of": sum(c.values()),
                        "table": {f"argon {x} / ours {y}": n for (x, y), n in sorted(c.items())}}
    from scripts.ablation import units
    from scripts.reread_analysis import all_units, r2_r3
    from scripts.v34_check import parts
    rp, rc = replaced("prospective"), replaced("calibration")
    us = [{**u, "cvs": [rc.get(u["id"], {}).get(cv.id, cv) for cv in u["cvs"]], "sample": "calibration"} for u in units()]
    for h, r in json.loads((PROS / "run_60.json").read_text()).items():
        it = r["items"][0]
        if it.get("card") and it.get("verification") and "v3" in it:
            card, cvs, alts = parts(it, h)
            us.append({"id": h, "label": None, "card": card, "cvs": [rp.get(h, {}).get(cv.id, cv) for cv in cvs], "alts": alts,
                       "sample": "prospective"})
    out["references_with_check"] = r2_r3(us)
    out["references_before"] = r2_r3(all_units("v9"))
    (CAL / "claim_results_score.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run() if (sys.argv[1:] or ["score"])[0] == "run" else score(), indent=1, ensure_ascii=False))

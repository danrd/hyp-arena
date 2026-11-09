"""Certainty-aware weight of meta-analysis records (specs/meta-and-nulls-2026-11-09.yaml, meta_certainty).

    ALLOW_PAID=1 python -m scripts.meta_certainty run     # -> calibration/meta_certainty.json
    python -m scripts.meta_certainty score                 # free
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from scripts.reread_v11 import CONFIG, items
from scripts.v34_check import CAL

OUT = CAL / "meta_certainty.json"
GRADE_RX = re.compile(r"(high|moderate|low|very[- ]low)[- ](certainty|quality)[^.]{0,40}(evidence|GRADE)|GRADE[^.]{0,80}?\b(high|moderate|low|very[- ]low)\b", re.I)
CERT_W = {"high": 1.0, "moderate": 1.0, "low": 0.5, "very_low": 0.25}
ROB_W = {"low": 1.0, "some_concerns": 0.75, "high": 0.5, "not_reported": 0.75}


def records():
    for pool in ("prospective", "calibration"):
        for h, as_of, card, cvs, logs in items(pool):
            cl = {x.id: x for x in card.claims}
            for cv in cvs:
                k = cl.get(cv.id)
                if not k or k.link in r3.PRECLINICAL_LINKS:
                    continue
                for r in cv.evidence:
                    if r3.record_design(r) == "meta_analysis" and r32.current_weight(r, k, False) > 0:
                        yield f"{h}|{cv.id}|{r.record_id.replace('PMID:', '')}", k, r


def grade_from_abstract(text: str):
    m = GRADE_RX.search(text or "")
    if not m:
        return None
    w = (m.group(1) or m.group(4) or "").lower().replace(" ", "_").replace("-", "_")
    return w if w in CERT_W else None


def run() -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask
    from hyparena.card.pipeline import _client
    from hyparena.tools import pmc, pubmed
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [t for t in records() if t[0] not in done]
    client, _ = _client(CONFIG, False, len(todo) * 3 + 5)
    tin = tout = 0
    for key, k, r in todo:
        p = key.split("|")[2]
        a = pubmed.fetch([p]).get(p, {})
        text = a.get("abstract", "")
        ft = pmc.excerpt(p)
        if ft:
            text += "\n\n[FULL TEXT: methods and results]\n" + ft
        log: list = []
        v, _ = ask(client, role="meta_certainty", family="deepseek", template="meta_certainty", version="v1",
                   variables={"claim": k, "qualifiers": ", ".join(f"{x}: {y}" for x, y in k.qualifiers.items() if y), "pmid": p,
                              "title": a.get("title", ""), "text": text},
                   validate=lambda x: [] if "certainty" in x else ['a "certainty" field'], rounds=2, log=log)
        v = v or {}
        q = v.get("quote") or ""
        done[key] = {**v, "quote_verbatim": bool(q) and " ".join(q.lower().split()) in " ".join(text.lower().split()),
                     "grade_regex": grade_from_abstract(a.get("abstract", "")), "full_text": bool(ft)}
        tin += sum(int(x.get("tokens_in") or 0) for x in log)
        tout += sum(int(x.get("tokens_out") or 0) for x in log)
        OUT.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    return {"records": len(done), "this_run": len(todo), "usd_offpeak": round(tin * 0.15e-6 + tout * 0.6e-6, 4)}


def factor(v: dict, variant: str):
    """The multiplier on the design weight of a meta-analysis record; None drops the record."""
    if variant == "current" or not v:
        return 1.0
    if variant == "certainty_and_pooled" and v.get("claim_outcome_pooled") == "no":
        return None
    c = v.get("grade_regex") or v.get("certainty")
    if c in CERT_W:
        return CERT_W[c]
    return ROB_W.get(v.get("risk_of_bias"), 0.75)


def score() -> dict:
    import scripts.record_weight_check as m
    from scripts.reread_analysis import all_units, r2_r3
    cert = json.loads(OUT.read_text())
    out = {"records": len(cert), "certainty_levels": dict(Counter(v.get("grade_regex") or v.get("certainty") for v in cert.values())),
           "risk_of_bias": dict(Counter(v.get("risk_of_bias") for v in cert.values())),
           "claim_outcome_pooled": dict(Counter(v.get("claim_outcome_pooled") for v in cert.values())),
           "quote_verbatim": sum(bool(v.get("quote_verbatim")) for v in cert.values())}
    rw = r32.record_weight
    for variant in ("current", "certainty", "certainty_and_pooled"):
        def patched(rec, cl, against, v34=False, variant=variant):
            w = rw(rec, cl, against, v34)
            if against or w <= 0 or r3.record_design(rec) != "meta_analysis":
                return w
            hit = [v for kk, v in cert.items() if kk.endswith("|" + rec.record_id.replace("PMID:", "")) and kk.split("|")[1] == cl.id]
            f = factor(hit[0], variant) if hit else 1.0
            return 0.0 if f is None else w * f
        r32.record_weight = patched
        try:
            out[variant] = r2_r3(all_units("v9"))
        finally:
            r32.record_weight = rw
    (CAL / "meta_certainty_score.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run() if (sys.argv[1:] or ["score"])[0] == "run" else score(), indent=1))

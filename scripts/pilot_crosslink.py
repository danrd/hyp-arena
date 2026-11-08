"""Pilot: cross-link reading in small batches, then the split reader (specs/balance-check-2026-11-08.yaml, pilot_crosslink).

    ALLOW_PAID=1 python -m scripts.pilot_crosslink run     # -> prospective/pilot_crosslink.json
    python -m scripts.pilot_crosslink score                 # free
"""
from __future__ import annotations

import json
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from scipy.stats import spearmanr

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification
from scripts.reread_v11 import CONFIG, items
from scripts.split_reader import relabel
from scripts.v34_check import CAL, PROS

ARGON = CAL.parents[1] / "reviews" / "argon-2026-11-08"
OUT = PROS / "pilot_crosslink.json"
BATCH = 10


def sample() -> list[str]:
    ans = json.loads((ARGON / "pack_8_answer.json").read_text())["trials"]
    n = {t["id"]: sum(len(set(l.get("pmids_for", []) + l.get("pmids_against", []))) for l in t["links"]) for t in ans}
    return sorted(n, key=lambda h: (-n[h], h))[:30]


def merge(cvs: list[ClaimVerification], cid: str) -> ClaimVerification:
    out = ClaimVerification(id=cid)
    for cv in cvs:
        out.evidence += cv.evidence
        out.counterevidence += cv.counterevidence
        out.no_stance += cv.no_stance
        out.refusals += cv.refusals
    return out


def run() -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask
    from hyparena.card.pipeline import _client
    from hyparena.card.verifier import verify_claim
    from hyparena.tools import pubmed
    want = set(sample())
    done = json.loads(OUT.read_text()) if OUT.exists() else {}
    tasks = []
    for h, as_of, card, cvs, logs in items("prospective"):
        if h not in want:
            continue
        chain = list(r3.chain(card))
        for cl in chain:
            if f"{h}|{cl.id}" in done:
                continue
            papers = list(dict.fromkeys(logs.get(cl.id, []) + [p for c in chain for p in logs.get(c.id, [])]))
            if papers:
                tasks.append((h, as_of, card, cl, papers))
    client, _ = _client(CONFIG, False, sum(len(t[4]) // BATCH + 3 for t in tasks) * 3 + 20)
    lock, tok = threading.Lock(), Counter()

    def one(t):
        h, as_of, card, cl, papers = t
        log: list = []
        parts_ = [verify_claim(client, "deepseek", frozenset({"google"}), cl, card, as_of, log=log, fallback="google",
                               expert_pmids=[(p, "cross-link reading") for p in papers[i:i + BATCH]], search="fixed",
                               template_version="v9")
                  for i in range(0, len(papers), BATCH)]
        cv = merge(parts_, cl.id)
        recs = cv.evidence + cv.counterevidence
        labels = {}
        if recs:
            meta = pubmed.fetch(sorted({r.record_id.replace("PMID:", "") for r in recs}))
            rows = [{"rid": f"r{i}", "pmid": r.record_id.replace("PMID:", ""), "quote": r.quote,
                     "title": meta.get(r.record_id.replace("PMID:", ""), {}).get("title", ""),
                     "abstract": meta.get(r.record_id.replace("PMID:", ""), {}).get("abstract", "")[:1200]} for i, r in enumerate(recs, 1)]
            value, _ = ask(client, role="relabel_context", family="google", template="relabel_context", version="v1",
                           variables={"claim": cl, "qualifiers": ", ".join(f"{k}: {v}" for k, v in cl.qualifiers.items() if v),
                                      "records": rows},
                           validate=lambda v: [] if isinstance(v.get("records"), list) else ['a "records" list'], rounds=2, log=log)
            lab = {x.get("rid"): x for x in (value or {}).get("records") or [] if isinstance(x, dict)}
            labels = {f"{rows[i]['pmid']}|{i}": lab.get(rows[i]["rid"]) for i in range(len(rows))}
        with lock:
            done[f"{h}|{cl.id}"] = {"cv": cv.model_dump(), "labels": labels, "papers": len(papers)}
            for x in log:
                fam = x.get("family") or ""
                tok[f"{fam}_in"] += int(x.get("tokens_in") or 0)
                tok[f"{fam}_out"] += int(x.get("tokens_out") or 0)
            OUT.write_text(json.dumps(done, ensure_ascii=False) + "\n")
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, tasks))
    usd = tok["deepseek_in"] * 0.15e-6 + tok["deepseek_out"] * 0.6e-6 + tok["google_in"] * 1.5e-6 + tok["google_out"] * 9e-6
    return {"links": len(done), "tokens": dict(tok), "usd": round(usd, 3)}


def pilot_cv(entry: dict, cl) -> ClaimVerification:
    cv = ClaimVerification.model_validate(entry["cv"])
    recs = cv.evidence + cv.counterevidence
    new_e, new_c = [], []
    for i, r in enumerate(recs):
        n = relabel(r, entry["labels"].get(f"{r.record_id.replace('PMID:', '')}|{i}"))
        if n is not None:
            (new_e if i < len(cv.evidence) else new_c).append(n)
    return cv.model_copy(update={"evidence": new_e, "counterevidence": new_c})


def score() -> dict:
    from scripts.pack8_analysis import signed
    from scripts.reread_analysis import reread
    ans = {t["id"]: t for t in json.loads((ARGON / "pack_8_answer.json").read_text())["trials"]}
    pilot = json.loads(OUT.read_text())
    second = reread("prospective", "v9")
    want = sample()
    data = {h: (card, cvs, alts) for h, (card, cvs, alts) in
            ((h, v) for h, v in ((h, __import__("scripts.v34_check", fromlist=["parts"]).parts(r["items"][0], h))
                                  for h, r in json.loads((PROS / "run_60.json").read_text()).items() if h in want))}
    out = {}
    for name in ("original", "second_v9", "pilot", "pilot_without_relabel"):
        ours, theirs, bal_o, bal_a, hits, keys, nrec, links = [], [], [], [], 0, 0, 0, 0
        for h in want:
            card, cvs, alts = data[h]
            claims = {c.id: c for c in card.claims}
            if name == "original":
                use = cvs
            elif name == "second_v9":
                use = [second.get(h, {}).get(cv.id, cv) for cv in cvs]
            else:
                use = [(pilot_cv(pilot[f"{h}|{cv.id}"], claims[cv.id]) if name == "pilot"
                        else ClaimVerification.model_validate(pilot[f"{h}|{cv.id}"]["cv"])) if f"{h}|{cv.id}" in pilot else cv
                       for cv in cvs]
            e = r32.evaluate(card, use, alts, v36=True)
            bal_o.append(-1.0 if e.gate != "pass" else e.chain_state)
            bal_a.append(ans[h]["balance"])
            by = {cv.id: cv for cv in use}
            for l in ans[h]["links"]:
                if l["id"] not in e.links:
                    continue
                ours.append(2 * e.links[l["id"]][0] - 1)
                theirs.append(signed(l))
                cv, cl = by.get(l["id"]), claims.get(l["id"])
                counting = {x.record_id.replace("PMID:", "") for s, lst in (("f", cv.evidence), ("a", cv.counterevidence))
                            for x in lst if r32.current_weight(x, cl, s == "a") > 0} if cv and cl else set()
                kp = set(l.get("pmids_for", []) + l.get("pmids_against", []))
                hits += len(kp & counting)
                keys += len(kp)
                nrec += len(counting)
                links += 1
        out[name] = {"recall_key_papers": f"{hits}/{keys} = {hits / keys:.2f}", "link_spearman": round(float(spearmanr(ours, theirs).statistic), 3),
                     "trial_spearman": round(float(spearmanr(bal_o, bal_a).statistic), 3), "counting_papers_per_link": round(nrec / links, 1),
                     "mean_balance": round(sum(bal_o) / len(bal_o), 3)}
    out["papers_read_per_link_pilot"] = round(sum(v["papers"] for v in pilot.values()) / len(pilot), 1)
    (CAL / "pilot_crosslink.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run() if (sys.argv[1:] or ["score"])[0] == "run" else score(), indent=1))

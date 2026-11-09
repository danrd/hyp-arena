"""Reader v12 pilot (specs/reader-v12-2026-11-08.yaml): a relevance filter before reading and an answer for every paper.

    ALLOW_PAID=1 python -m scripts.reader_v12 run --part dev|holdout [--rev v12]   # -> prospective/reader_v12_<part>.json
    python -m scripts.reader_v12 score --part dev|holdout                           # free
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification
from scripts.pilot_crosslink import merge
from scripts.pilot_crosslink import sample as pilot_trials
from scripts.reread_v11 import CONFIG, items
from scripts.v34_check import CAL, PROS

ARGON = CAL.parents[1] / "reviews" / "argon-2026-11-08"
BATCH = 10
QUANT = re.compile(r"95\s*%\s*CI|confidence interval|p\s*[<=>≤]\s*0?\.\d|\b(WMD|SMD|MD|OR|RR|HR)\b\s*[=:,]?\s*-?\d"
                   r"|\b(improv|reduc|increas|decreas|lower|higher|no (significant )?(effect|difference|benefit)|did not|"
                   r"significant|effective|beneficial)\w*", re.I)   # revision 1 (dev): result words count too
REVIEWISH = ("Review", "Systematic Review", "Editorial", "Comment")


def rule_pass(meta: dict) -> bool:
    pts = meta.get("pubtypes") or []
    if any("Meta-Analysis" in p for p in pts):
        return True
    if any(p in REVIEWISH for p in pts):
        return bool(QUANT.search(meta.get("abstract", "")))
    return True


def targets(part: str) -> list[tuple]:
    """(key, unit, as_of, card, claim, papers of its own search)."""
    if part == "dev":
        key = json.loads((ARGON / "pack_9_key.json").read_text())
        want = {(v["unit"], v["claim"]) for v in key.values()}
        trials = {u for u, _ in want}
    else:
        trials, want = set(pilot_trials()), None
    out = []
    for h, as_of, card, cvs, logs in items("prospective"):
        if h not in trials:
            continue
        chain = list(r3.chain(card))
        for cl in chain:
            if (want is None or (h, cl.id) in want) and logs.get(cl.id):
                papers = logs[cl.id]
                if part == "crosslink":                  # the union of the chain searches of the trial, own papers first
                    papers = list(dict.fromkeys(papers + [p for c in chain for p in logs.get(c.id, [])]))
                out.append((f"{h}|{cl.id}", h, as_of, card, cl, papers))
    return out


def run(part: str, rev: str) -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.card.llm import ask, parse_fullest
    from hyparena.card.pipeline import _client
    from hyparena.card.verifier import verify_claim
    from hyparena.tools import pubmed
    out_p = PROS / f"reader_v12_{part}_{rev}.json"
    done = json.loads(out_p.read_text()) if out_p.exists() else {}
    tasks = [t for t in targets(part) if t[0] not in done]
    client, _ = _client(CONFIG, False, len(tasks) * 12 + 20)
    lock, tok = threading.Lock(), Counter()

    def one(t):
        k, h, as_of, card, cl, papers = t
        log: list = []
        meta = pubmed.fetch(papers)
        papers = [p for p in papers if meta.get(p, {}).get("abstract")]
        decision = {p: ("rule_drop" if not rule_pass(meta[p]) else "") for p in papers}
        cand = [p for p in papers if not decision[p]]
        if cand:
            rows = [{"pmid": p, "title": meta[p].get("title", ""), "start": meta[p].get("abstract", "")[:600]} for p in cand]
            value, _ = ask(client, role="relevance_filter", family="deepseek", template="relevance_filter", version=os.environ.get("FILTER_VERSION", "v2"),
                           variables={"claim": cl, "qualifiers": ", ".join(f"{a}: {b}" for a, b in cl.qualifiers.items() if b),
                                      "papers": rows},
                           validate=lambda v: [] if isinstance(v.get("papers"), list) else ['a "papers" list'], rounds=2, log=log)
            ans = {str(x.get("pmid", "")).replace("PMID:", "").strip(): x.get("own_result") for x in (value or {}).get("papers") or []
                   if isinstance(x, dict)}
            for p in cand:
                decision[p] = {"yes": "yes", "no": "filter_drop"}.get(ans.get(p), "unsure")
        kept = [p for p in papers if decision[p] in ("yes", "unsure")]
        answered, parts_ = {}, []

        def read(batch):
            n0 = len(log)
            parts_.append(verify_claim(client, "deepseek", frozenset({"google"}), cl, card, as_of, log=log, fallback="google",
                                       expert_pmids=[(p, "reader v12") for p in batch], search="fixed", template_version=rev,
                                       check_subgroups=False))
            for x in log[n0:]:
                if x.get("template") == f"verify_claim/{rev}" and x.get("reply"):
                    v = parse_fullest(x["reply"]) or {}
                    for e in v.get("papers") or []:
                        if isinstance(e, dict):
                            answered[str(e.get("pmid", "")).replace("PMID:", "").strip()] = e.get("finding")
        for i in range(0, len(kept), BATCH):
            read(kept[i:i + BATCH])
        missing = [p for p in kept if p not in answered]
        if missing:
            for i in range(0, len(missing), BATCH):
                read(missing[i:i + BATCH])
        cv = merge(parts_, cl.id)
        with lock:
            done[k] = {"cv": cv.model_dump(), "decision": decision, "answered": answered,
                       "skipped": [p for p in kept if p not in answered], "papers": len(papers), "kept": len(kept)}
            for x in log:
                tok[f"{x.get('family') or ''}_in"] += int(x.get("tokens_in") or 0)
                tok[f"{x.get('family') or ''}_out"] += int(x.get("tokens_out") or 0)
            out_p.write_text(json.dumps(done, ensure_ascii=False) + "\n")
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, tasks))
    usd = tok["deepseek_in"] * 0.15e-6 + tok["deepseek_out"] * 0.6e-6 + tok["google_in"] * 1.5e-6 + tok["google_out"] * 9e-6
    return {"links": len(done), "this_run": len(tasks), "tokens": dict(tok), "usd": round(usd, 4)}


def score(part: str, rev: str) -> dict:
    res = json.loads((PROS / f"reader_v12_{part}_{rev}.json").read_text())
    vol = {"papers_per_link": round(sum(v["papers"] for v in res.values()) / len(res), 1),
           "kept_per_link": round(sum(v["kept"] for v in res.values()) / len(res), 1),
           "decisions": dict(Counter(d for v in res.values() for d in v["decision"].values())),
           "answered_share": round(sum(len(v["answered"]) for v in res.values()) / max(1, sum(v["kept"] for v in res.values())), 3),
           "skipped_after_retry": sum(len(v["skipped"]) for v in res.values())}
    if part == "crosslink":
        out = score_pack8(res)
        out["pack9"] = score_pack9(res)
        return {**vol, **out}
    if part == "dev":
        return {**vol, **score_pack9(res)}
    return {**vol, **score_pack8(res)}


def score_pack9(res: dict) -> dict:
    if True:
        ans = {i["id"]: i for i in json.loads((ARGON / "pack_9_answer.json").read_text())["items"]}
        key = json.loads((ARGON / "pack_9_key.json").read_text())
        tp = fn = fp = ok = 0
        drop = Counter()
        for iid, it in ans.items():
            r = res.get(f"{key[iid]['unit']}|{key[iid]['claim']}")
            if not r:
                continue
            cv = ClaimVerification.model_validate(r["cv"])
            recs = {}
            for side, lst in (("for", cv.evidence), ("against", cv.counterevidence)):
                for x in lst:
                    recs.setdefault(x.record_id.replace("PMID:", ""), side)
            for p in it["papers"]:
                if p["finding"] in ("for", "against"):
                    if r["decision"].get(p["pmid"]) in ("rule_drop", "filter_drop"):
                        drop[r["decision"][p["pmid"]]] += 1
                    if p["pmid"] in recs:
                        tp += 1
                        ok += recs[p["pmid"]] == p["finding"]
                    else:
                        fn += 1
                elif p["pmid"] in recs:
                    fp += 1
        return {"recall": f"{tp}/{tp + fn} = {tp / (tp + fn):.2f}", "precision": f"{tp}/{tp + fp} = {tp / max(1, tp + fp):.2f}",
                "direction": f"{ok}/{tp}", "gold_findings_dropped": dict(drop)}


def score_pack8(res: dict) -> dict:
    from scipy.stats import spearmanr
    from scripts.pack8_analysis import signed
    from scripts.v34_check import parts
    ans = {t["id"]: t for t in json.loads((ARGON / "pack_8_answer.json").read_text())["trials"]}
    run_ = json.loads((PROS / "run_60.json").read_text())
    ours, theirs, bo, ba, hits, keys = [], [], [], [], 0, 0
    for h in pilot_trials():
        card, cvs, alts = parts(run_[h]["items"][0], h)
        use = [ClaimVerification.model_validate(res[f"{h}|{cv.id}"]["cv"]) if f"{h}|{cv.id}" in res else cv for cv in cvs]
        e = r32.evaluate(card, use, alts, v36=True)
        bo.append(-1.0 if e.gate != "pass" else e.chain_state)
        ba.append(ans[h]["balance"])
        by, claims = {cv.id: cv for cv in use}, {c.id: c for c in card.claims}
        for l in ans[h]["links"]:
            if l["id"] not in e.links:
                continue
            ours.append(2 * e.links[l["id"]][0] - 1)
            theirs.append(signed(l))
            cv, cl = by.get(l["id"]), claims.get(l["id"])
            cnt = {x.record_id.replace("PMID:", "") for s, lst in (("f", cv.evidence), ("a", cv.counterevidence)) for x in lst
                   if r32.current_weight(x, cl, s == "a") > 0} if cv and cl else set()
            kp = set(l.get("pmids_for", []) + l.get("pmids_against", []))
            hits += len(kp & cnt)
            keys += len(kp)
    return {"recall_key_papers": f"{hits}/{keys} = {hits / keys:.2f}",
            "link_spearman": round(float(spearmanr(ours, theirs).statistic), 3), "trial_spearman": round(float(spearmanr(bo, ba).statistic), 3)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("--part", choices=["dev", "holdout", "crosslink"], required=True)
    ap.add_argument("--rev", default="v12")
    a = ap.parse_args()
    res = run(a.part, a.rev) if a.cmd == "run" else score(a.part, a.rev)
    (CAL / f"reader_v12_{a.part}_{a.rev}_{a.cmd}.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))

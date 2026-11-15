"""Confirming run of a reader without searching again (specs/reading/benchmark-reading-2026-11-12.yaml, reader_v16_confirming):
the saved runs of the filtered search on the 30 trials of pack 18 (calibration run_*_n12.json) are read again with
another reader on exactly the papers each claim and each proposed alternative read then; cards, searches and proposed
alternatives are kept, so only the reader changes. The result is a run file of the same shape (run_*_<tag>.json), scored
by the search benchmark (gold papers that became records) and by the AUC of the evidence balance against the outcomes.

    ALLOW_PAID=1 MAX_USD=1.2 python -m scripts.reading.reader_replay run [--version v16 --batch 10 --tag n13r]
    ALLOW_PAID=1 MAX_USD=1.0 python -m scripts.reading.reader_replay cross --tag n14x   # cross-link reading over n13r
    python -m scripts.reading.reader_replay score [--tag n13r]                      # free
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor

from hyparena.card.models import Claim, ClaimVerification, HypothesisCard
from scripts.common.v34_check import CAL

UNITS = CAL.parents[1] / "reviews" / "argon-2026-11-12" / "pack_18_units.txt"
BASE = "n12"
CONFIG = "configs/v3-flash-n13.yaml"


def _searched(run: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in run["calls"]:
        if c.get("kind") == "search" and c.get("claim"):
            out.setdefault(c["claim"], [])
            out[c["claim"]] += [p for p in c.get("pmids") or [] if p not in out[c["claim"]]]
    return out


def replay_one(client, run: dict, version: str, log: list) -> dict:
    from hyparena.scoring.rules import finalize
    from hyparena.reading.verifier import verify, verify_claim
    from hyparena.scoring import rules_v3
    from hyparena.search.search import ALTERNATIVE_NOTE
    it = run["items"][0]
    card = HypothesisCard.model_validate(it["card"])
    as_of, writer = run["meta"].get("as_of"), run["meta"].get("writer") or "unknown"
    searched = _searched(run)
    expert = {cid: [(p, "replay of the saved search") for p in pm] for cid, pm in searched.items()}
    ver = verify(client, ["deepseek"], writer, card, as_of=as_of, log=log, expert_sources=expert, fallback_families=["google"],
                 search="fixed", template_version=version, probes=False)
    verification = finalize(card, ver)
    alt_ver = {}
    for alt in card.proposed_alternatives:
        if not alt.support_pmids:
            continue
        ac = Claim(id=alt.id, subject=alt.subject, relation=alt.relation, object=alt.object, qualifiers=alt.qualifiers,
                   role="premise", source_span="", note=ALTERNATIVE_NOTE)
        pm = searched.get(alt.id) or list(alt.support_pmids)
        alt_ver[alt.id] = verify_claim(client, "deepseek", frozenset({writer}), ac, card, as_of, log=log, fallback="google",
                                       expert_pmids=[(p, "replay of the saved search") for p in pm], search="fixed",
                                       template_version=version)
    new = json.loads(json.dumps(run))
    ni = new["items"][0]
    ni["verification"] = verification.model_dump(by_alias=True)
    ni["v3"] = rules_v3.evaluate(card, verification.claims, alt_ver).as_dict()
    ni["v3_alternatives"] = {k: v.model_dump(by_alias=True) for k, v in alt_ver.items()}
    new["calls"] = [c for c in run["calls"] if c.get("kind") == "search"] + [x for x in log if x.get("kind") == "llm"]
    new["meta"] = {**run["meta"], "replay_of": BASE, "reader": version, "config": CONFIG}
    return new


def _queries(run: dict, cid: str) -> list[str]:
    q = [c for c in run["calls"] if c.get("kind") == "search_plan" and c.get("claim") == cid]
    return list(q[0].get("guarded") or q[0].get("model_queries") or []) if q else []


def cross_one(client, run: dict, base_run: dict, version: str, log: list) -> dict:
    """Cross-link reading (as hyparena/reading/cross_link.py, run over a saved replay): every claim of the hypothesis (outcome and steps) also reads the papers the hypothesis's other
    searches found (mostly those of its proposed alternatives). The cheap relevance model rates those papers for the claim
    (as in the search) and the claim reads, besides its own papers, every one rated 3 filled up to 10 with those rated 2.
    The proposed alternatives keep their own reading of the base replay."""
    from hyparena.scoring.rules import finalize
    from hyparena.scoring import rules_v3
    from hyparena.search import search as srch, search_rank as rank
    from hyparena.tools import pubmed
    it = run["items"][0]
    card = HypothesisCard.model_validate(it["card"])
    as_of, writer = run["meta"].get("as_of"), run["meta"].get("writer") or "unknown"
    searched = _searched(run)
    everything = list(dict.fromkeys(p for v in searched.values() for p in v))
    recs = pubmed.fetch(everything)
    expert, added = {}, {}
    for c in card.claims:
        if c.part == "premise":
            continue
        own = searched.get(c.id, [])
        extra = [p for p in everything if p not in own and (recs.get(p) or {}).get("abstract")]
        scores = srch.relevance(client, frozenset({writer}), c, card, _queries(run, c.id), extra, recs, log=log) if extra else {}
        pick = rank.select(extra, scores, fill=srch.FILL, cap=srch.CAP)
        added[c.id] = {"extra": len(extra), "ratings": {k: sum(1 for v in scores.values() if v == k) for k in (0, 1, 2, 3)},
                       "read": pick}
        expert[c.id] = [(p, "cross-link: another search of the hypothesis") for p in pick]
    from hyparena.card.models import Verification
    from hyparena.reading.verifier import verify_claim
    bi = base_run["items"][0]
    base_cvs = {c["id"]: ClaimVerification.model_validate(c) for c in bi["verification"]["claims"]}
    claims = {c.id: c for c in card.claims}
    merged = []
    for cid, cv in base_cvs.items():                     # the base replay's reading of the claim's own papers is kept
        if expert.get(cid):
            new_cv = verify_claim(client, "deepseek", frozenset({writer}), claims[cid], card, as_of, log=log, fallback="google",
                                  expert_pmids=expert[cid], search="fixed", template_version=version)
            seen = {r.record_id for r in cv.evidence + cv.counterevidence}
            cv.evidence += [r for r in new_cv.evidence if r.record_id not in seen]
            cv.counterevidence += [r for r in new_cv.counterevidence if r.record_id not in seen]
            cv.no_stance += new_cv.no_stance
        merged.append(cv)
    verification = finalize(card, Verification(card_id=card.id, claims=merged,
                                               searched_pmids=bi["verification"].get("searched_pmids") or []))
    alt_ver = {k: ClaimVerification.model_validate(v) for k, v in (bi.get("v3_alternatives") or {}).items()}
    new = json.loads(json.dumps(base_run))
    ni = new["items"][0]
    ni["verification"] = verification.model_dump(by_alias=True)
    ni["v3"] = rules_v3.evaluate(card, verification.claims, alt_ver).as_dict()
    new["calls"] = [c for c in run["calls"] if c.get("kind") == "search"] + [x for x in log if x.get("kind") == "llm"]
    new["meta"] = {**base_run["meta"], "cross_link": added}
    return new


def run_cross(version: str, batch: int, tag: str, base_tag: str = "n13r") -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.pipeline import _client
    from hyparena.reading import verifier
    verifier.READ_BATCH = batch
    ids = set(UNITS.read_text().split())
    client, _ = _client(CONFIG, False, 6000)
    done = {}
    for s in (1, 2, 3, 4, 5):
        src = json.loads((CAL / f"run_{s}_{BASE}.json").read_text())
        base = json.loads((CAL / f"run_{s}_{base_tag}.json").read_text())
        out_f = CAL / f"run_{s}_{tag}.json"
        out = json.loads(out_f.read_text()) if out_f.exists() else {}
        todo = [u for u in base if u in ids and u not in out]

        def one(u):
            log: list = []
            return u, cross_one(client, src[u], base[u], version, log)
        with ThreadPoolExecutor(3) as ex:
            for u, r in ex.map(one, todo):
                out[u] = r
                out_f.write_text(json.dumps(out, ensure_ascii=False, default=str))
        done[s] = len(out)
    return {"units": done}


def run(version: str, batch: int, tag: str) -> dict:
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    from hyparena.pipeline import _client
    from hyparena.reading import verifier
    verifier.READ_BATCH = batch
    ids = set(UNITS.read_text().split())
    client, _ = _client(CONFIG, False, 4000)
    done = {}
    for s in (1, 2, 3, 4, 5):
        src = json.loads((CAL / f"run_{s}_{BASE}.json").read_text())
        out_f = CAL / f"run_{s}_{tag}.json"
        out = json.loads(out_f.read_text()) if out_f.exists() else {}
        todo = [u for u in src if u in ids and u not in out and src[u]["items"][0].get("card")]

        def one(u):
            log: list = []
            return u, replay_one(client, src[u], version, log)
        with ThreadPoolExecutor(3) as ex:
            for u, r in ex.map(one, todo):
                out[u] = r
                out_f.write_text(json.dumps(out, ensure_ascii=False, default=str))
        done[s] = len(out)
    return {"units": done}


def balance_auc(tag: str) -> dict:
    from hyparena.alternatives import alternatives_d
    from hyparena.scoring import rules_v32 as r32
    from scripts.common.ablation import auc_of
    from hyparena.whole_system.backtest import bootstrap_tied_auc
    ids = set(UNITS.read_text().split())
    vals = []
    for s in (1, 2, 3, 4, 5):
        us = {u["id"]: u for u in json.loads((CAL / f"units_{s}.json").read_text())}
        f = CAL / f"run_{s}_{tag}.json"
        if not f.exists():
            continue
        for h, r in json.loads(f.read_text()).items():
            it = r["items"][0]
            if h not in ids or us.get(h, {}).get("label") not in (0, 1) or "v3" not in it:
                continue
            card = alternatives_d.apply(h, HypothesisCard.model_validate(it["card"]))
            cvs = [ClaimVerification.model_validate(c) for c in it["verification"]["claims"]]
            alts = {a: ClaimVerification.model_validate(v) for a, v in (it.get("v3_alternatives") or {}).items()}
            e = r32.evaluate(card, cvs, alts, v36=True)
            vals.append((-1.0 if e.gate != "pass" else e.chain_state, us[h]["label"]))
    pos, neg = [(v, 0) for v, l in vals if l == 1], [(v, 0) for v, l in vals if l == 0]
    lo, hi = bootstrap_tied_auc(pos, neg) if pos and neg else (None, None)
    return {"trials": len(vals), "auc": auc_of(vals), "ci95": [round(lo, 3), round(hi, 3)] if lo is not None else None}


def records(tag: str) -> dict:
    n = 0
    for s in (1, 2, 3, 4, 5):
        f = CAL / f"run_{s}_{tag}.json"
        if f.exists():
            for r in json.loads(f.read_text()).values():
                v = r["items"][0].get("verification") or {}
                n += sum(len(c.get("evidence") or []) + len(c.get("counterevidence") or []) for c in v.get("claims") or [])
    return {"records": n}


def score(tag: str) -> dict:
    from scripts.reading.bench_reading import DIR
    out = {}
    keep = (DIR / "bench_search_score.json").read_text()       # bench_search.score writes its file: the saved one is put back
    for t in (BASE, tag):
        os.environ["SEARCH_RUNS"] = f"run_*_{t}.json"
        import importlib
        from scripts.search import bench_search
        importlib.reload(bench_search)
        b = bench_search.score()
        out[t] = {"read_must": b["all"]["read_must"], "read_must_holdout": b["holdout"]["read_must"],
                  "recall_must": b["all"]["recall_must"], **balance_auc(t), **records(t)}
    (DIR / "bench_search_score.json").write_text(keep)
    (DIR / f"reader_replay_{tag}.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["run", "cross", "score"])
    ap.add_argument("--version", default="v16")
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--tag", default="n13r")
    ap.add_argument("--base", default="n13r", help="cross: the replay whose own reading is kept")
    a = ap.parse_args()
    fn = {"run": lambda: run(a.version, a.batch, a.tag), "cross": lambda: run_cross(a.version, a.batch, a.tag, a.base),
          "score": lambda: score(a.tag)}[a.cmd]
    print(json.dumps(fn(), indent=1, default=str))


if __name__ == "__main__":
    main()

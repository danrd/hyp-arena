"""Search benchmark (specs/benchmark-search-2026-11-12.yaml) on Argon pack 18: 30 calibration trials. Free, no model call.

    python -m scripts.bench_search check   # PubMed E-utilities: every gold PMID exists, its date on or before T (cached)
    python -m scripts.bench_search score   # recall of our saved searches, closest prior work, novelty agreement

Gold: Argon's papers per trial (prior_trial, direct, step, against, review; up to 5 must_find) and the closest prior work
with a novelty level. A gold PMID that PubMed does not know, or whose earliest date is after T, is
dropped and counted (earliest = electronic, print or PubMed entry date: when it became public); a year that differs from PubMed's is counted, the paper kept.

Ours: the saved searches of the calibration runs (longevity-kg hypothesis_sources/calibration/run_{s}_v10.json, method v3,
config v3-flash-n10, search 'model', date guard T): every PMID the search returned for each claim and alternative, before
reading. A paper is "found" when any search of the trial returned it; "found on its link" when a search of a claim with the
matching link returned it (gold step -> delivery / engagement / pathway / effect; the rest -> outcome); "read" when it
became a record of a claim (evidence or counterevidence). Our novelty level is the run's `indicators.novelty`.

Outputs: longevity-kg/reviews/argon-2026-11-12/pack_18_pubmed.json (cache), bench_search_score.json.
"""
from __future__ import annotations

import glob
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

KG = Path(__file__).resolve().parents[2] / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-12"
CAL = KG / "hypothesis_sources" / "calibration"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
STEP_LINKS = {"delivery", "engagement", "pathway", "effect"}
CATS = ("prior_trial", "direct", "step", "against", "review")
# novelty ladders on one scale, nearer the known first; Argon's 'new' (nothing close) = our three top levels
ARGON_RANK = {"known_result": 0, "new_context": 1, "translation": 2, "analog": 3, "new": 4}
OURS_RANK = {"known_result": 0, "new_context": 1, "translation": 2, "analog": 3,
             "new_mechanism": 4, "new_combination": 4, "new_link": 4}


def gold_answer(original: bool = False) -> dict:
    """Argon's search gold by trial; with the PMIDs corrected by pack 21 when that file exists (pack21_pmid_fix.py apply)."""
    fixed = DIR / "pack_18_answer_fixed.json"
    f = fixed if fixed.exists() and not original else DIR / "pack_18_answer.json"
    return {i["id"]: i for i in json.loads(f.read_text())["items"]}


def _load() -> tuple[dict, dict, dict]:
    ans = gold_answer()
    key = json.loads((DIR / "pack_18_key.json").read_text())
    runs = {}
    for f in sorted(glob.glob(str(CAL / os.environ.get("SEARCH_RUNS", "run_*_v10.json")))):   # SEARCH_RUNS: another run set
        runs.update(json.loads(Path(f).read_text()))
    return ans, key, runs


def _date(s: str) -> str | None:
    """'2019 Mar 5' / '2019 Mar' / '2019' / '2019 Spring' -> the earliest ISO day it can mean (as PubMed's pdat range)."""
    p = (s or "").replace("-", " ").split()
    if not p or not p[0][:4].isdigit():
        return None
    y, m, d = p[0][:4], 1, 1
    if len(p) > 1 and p[1][:3].lower() in MONTHS:
        m = MONTHS[p[1][:3].lower()]
        if len(p) > 2 and p[2].isdigit():
            d = int(p[2])
    return f"{y}-{m:02d}-{d:02d}"


def summaries(pmids: list[str], cache: dict) -> list[str]:
    """esummary of the PMIDs not yet in `cache` (exists, dates, earliest date, title, first author); returns those fetched."""
    todo = [p for p in pmids if p not in cache]
    for k in range(0, len(todo), 100):
        batch = todo[k:k + 100]
        url = EUTILS + "?" + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(batch), "retmode": "json"})
        res = json.loads(urllib.request.urlopen(url, timeout=60).read())["result"]
        for p in batch:
            r = res.get(p)
            if not r or r.get("error"):
                cache[p] = {"exists": False}
                continue
            entrez = next((h["date"][:10].replace("/", "-") for h in r.get("history", []) if h.get("pubstatus") == "entrez"), "")
            dates = [d for d in (_date(r.get("epubdate", "")), _date(r.get("pubdate", "")), entrez or None) if d]
            cache[p] = {"exists": True, "pubdate": r.get("pubdate", ""), "epubdate": r.get("epubdate", ""), "entrez": entrez,
                        "earliest": min(dates) if dates else None, "title": r.get("title", ""),
                        "first_author": (r.get("authors") or [{}])[0].get("name", ""), "journal": r.get("source", ""),
                        "pubtypes": r.get("pubtype", [])}
        time.sleep(0.4)
    return todo


def check() -> dict:
    """esummary for every gold PMID (papers and closest prior work); cached in pack_18_pubmed.json."""
    ans, _, _ = _load()
    pmids = sorted({p["pmid"] for i in ans.values() for p in i["papers"]} |
                   {i["closest_prior_work"]["pmid"] for i in ans.values() if i["closest_prior_work"].get("pmid")})
    f = DIR / "pack_18_pubmed.json"
    cache = json.loads(f.read_text()) if f.exists() else {}
    todo = summaries(pmids, cache)
    f.write_text(json.dumps(cache, indent=1, ensure_ascii=False) + "\n")
    return {"pmids": len(pmids), "fetched": len(todo), "not_in_pubmed": sum(not v["exists"] for v in cache.values())}


def _ours(run: dict) -> dict:
    it = run["items"][0]
    links = {c["id"]: c.get("link") for c in ((it.get("card") or {}).get("claims") or [])}
    by_claim, alt = defaultdict(set), set()
    for c in run["calls"]:
        if c.get("kind") != "search":
            continue
        pm = set(c.get("pmids") or [])
        if c.get("claim"):
            by_claim[c["claim"]] |= pm
        else:
            alt |= pm
    read = {e["record_id"].split(":", 1)[-1] for cv in ((it.get("verification") or {}).get("claims") or [])
            for e in (cv.get("evidence") or []) + (cv.get("counterevidence") or [])}
    outcome = set().union(*[v for k, v in by_claim.items() if links.get(k) == "outcome"] or [set()])
    step = set().union(*[v for k, v in by_claim.items() if links.get(k) in STEP_LINKS] or [set()])
    return {"all": set().union(alt, *by_claim.values()), "outcome": outcome, "step": step, "read": read,
            "has_step_claim": any(links.get(k) in STEP_LINKS for k in by_claim),
            "novelty": "known_result" if it["outcome"] == "known_result" else (it.get("indicators") or {}).get("novelty"),
            "status": it["outcome"], "n_returned": len(set().union(alt, *by_claim.values()))}


WORDS_OFF = set("the a an of in on and or to for with by from as at is are was were be that this these those it its into than "
                "after before during not no effect effects study trial randomized controlled results older adults elderly people "
                "patients among between showing significantly showed week weeks year years group groups compared improved "
                "increased reduced review systematic clinical human humans months".split())


def _content(s: str) -> set:
    return {w[:6] for w in re.findall(r"[a-z0-9]{4,}", (s or "").lower())} - {w[:6] for w in WORDS_OFF}


def described() -> dict:
    """Is the paper behind a gold PMID the paper the gold describes? The share of the content words of Argon's description
    (`shows`) that the PubMed title and abstract contain; under AS_DESCRIBED the PMID points to another paper (a wrong
    number) and is dropped. Written into pack_18_pubmed.json (`as_described`)."""
    from hyparena.tools import pubmed
    ans, _, _ = _load()
    f = DIR / "pack_18_pubmed.json"
    pm = json.loads(f.read_text())
    desc = {}
    for g in ans.values():
        for p in g["papers"]:
            desc[p["pmid"]] = p.get("shows", "")
        cp = g["closest_prior_work"]
        if cp.get("pmid"):
            desc.setdefault(cp["pmid"], " ".join(str(v) for k, v in cp.items() if k != "pmid"))
    ids = [p for p in desc if pm.get(p, {}).get("exists")]
    rec = {}
    for i in range(0, len(ids), 50):
        rec.update(pubmed.fetch(ids[i:i + 50]))
    for p in ids:
        a = _content(desc[p])
        b = _content(f"{(rec.get(p) or {}).get('title') or pm[p].get('title', '')} {(rec.get(p) or {}).get('abstract') or ''}")
        pm[p]["as_described"] = round(len(a & b) / len(a), 2) if a else None
    f.write_text(json.dumps(pm, indent=1, ensure_ascii=False) + "\n")
    bad = [p for p in ids if pm[p]["as_described"] is not None and pm[p]["as_described"] < AS_DESCRIBED]
    return {"checked": len(ids), "another_paper": len(bad)}


AS_DESCRIBED = 0.25


def valid(pm: dict, pmid: str) -> bool:
    """A gold PMID counts when it is in PubMed and its paper is the one the gold describes."""
    i = pm.get(pmid, {})
    return bool(i.get("exists")) and (i.get("as_described") is None or i["as_described"] >= AS_DESCRIBED)


def _rows(ans: dict, key: dict, runs: dict, pm: dict) -> tuple[list[dict], list[dict], Counter]:
    papers, trials, drop = [], [], Counter()
    for sid, g in sorted(ans.items()):
        k = key[sid]
        o = _ours(runs[k["unit"]])
        for p in g["papers"]:
            info = pm.get(p["pmid"], {})
            if not info.get("exists"):
                drop["not_in_pubmed"] += 1
                continue
            if not valid(pm, p["pmid"]):
                drop["another_paper"] += 1
                continue
            if info["earliest"] and info["earliest"] > k["T"]:
                drop["after_T"] += 1
                continue
            if str(p.get("year")) != (info.get("earliest") or "")[:4] and str(p.get("year")) not in (info.get("pubdate", "")[:4],):
                drop["year_differs_kept"] += 1
            on_link = o["step"] if p["category"] == "step" or (p["category"] == "against" and p.get("step")) else o["outcome"]
            papers.append({"sid": sid, "pmid": p["pmid"], "cat": p["category"], "must": bool(p.get("must_find")),
                           "pop": p.get("population"), "holdout": k["holdout"], "found": p["pmid"] in o["all"],
                           "on_link": p["pmid"] in on_link, "read": p["pmid"] in o["read"]})
        cp = g["closest_prior_work"].get("pmid") or ""
        cinfo = pm.get(cp, {})
        cp_ok = valid(pm, cp) and not (cinfo.get("earliest") and cinfo["earliest"] > k["T"])
        trials.append({"sid": sid, "short": k["short"], "holdout": k["holdout"], "outcome": (k.get("outcome") or {}).get("label"),
                       "argon_level": g["novelty_level"], "our_level": o["novelty"], "cp_valid": cp_ok,
                       "cp_found": cp_ok and cp in o["all"], "cp_read": cp_ok and cp in o["read"],
                       "n_returned": o["n_returned"], "status": o["status"], "has_step_claim": o["has_step_claim"]})
    return papers, trials, drop


def _share(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def _wkappa(pairs: list[tuple[int, int]], k: int = 5) -> float | None:
    """Linear-weighted Cohen's kappa on ranks 0..k-1."""
    if not pairs:
        return None
    n = len(pairs)
    w = lambda i, j: 1 - abs(i - j) / (k - 1)
    po = sum(w(a, b) for a, b in pairs) / n
    ma, mb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ma[i] * mb[j] * w(i, j) for i in range(k) for j in range(k)) / n / n
    return round((po - pe) / (1 - pe), 3) if pe < 1 else None


def _measures(papers: list[dict], trials: list[dict]) -> dict:
    must = [p for p in papers if p["must"]]
    pairs = [(OURS_RANK[t["our_level"]], ARGON_RANK[t["argon_level"]]) for t in trials
             if t["our_level"] in OURS_RANK and t["argon_level"] in ARGON_RANK]
    return {
        "recall_must": _share([p["found"] for p in must]),
        "recall_must_on_link": _share([p["on_link"] for p in must]),
        "read_must": _share([p["read"] for p in must]),
        "recall_all": _share([p["found"] for p in papers]),
        "recall_by_category": {c: {"n": sum(p["cat"] == c for p in papers), "found": _share([p["found"] for p in papers if p["cat"] == c]),
                                   "read": _share([p["read"] for p in papers if p["cat"] == c])} for c in CATS},
        "trials_with_a_must_found": _share([any(p["found"] for p in must if p["sid"] == t["sid"]) for t in trials
                                            if any(p["sid"] == t["sid"] for p in must)]),
        "prior_work_found": _share([t["cp_found"] for t in trials if t["cp_valid"]]),
        "prior_work_read": _share([t["cp_read"] for t in trials if t["cp_valid"]]),
        "novelty_wkappa": _wkappa(pairs),
        "novelty_ours_farther": _share([a > b for a, b in pairs]),
        "novelty_ours_nearer": _share([a < b for a, b in pairs]),
        "against_found": _share([p["found"] for p in papers if p["cat"] == "against"]),
        "n_papers": len(papers), "n_must": len(must), "n_trials": len(trials), "n_novelty_pairs": len(pairs),
    }


def score() -> dict:
    ans, key, runs = _load()
    f = DIR / "pack_18_pubmed.json"
    if not f.exists():
        check()
    pm = json.loads(f.read_text())
    papers, trials, drop = _rows(ans, key, runs, pm)
    rng = random.Random(20261112)
    sids = sorted({t["sid"] for t in trials})
    boots = defaultdict(list)
    for _ in range(2000):
        pick = [rng.choice(sids) for _ in sids]
        m = _measures([p for s in pick for p in papers if p["sid"] == s], [t for s in pick for t in trials if t["sid"] == s])
        for k in ("recall_must", "recall_must_on_link", "recall_all", "prior_work_found", "novelty_wkappa", "novelty_ours_farther"):
            if m[k] is not None:
                boots[k].append(m[k])
    ci = {k: [round(sorted(v)[int(0.025 * len(v))], 3), round(sorted(v)[int(0.975 * len(v)) - 1], 3)] for k, v in boots.items()}
    out = {
        "gold_check": dict(drop) | {"papers_given": sum(len(i["papers"]) for i in ans.values()),
                                    "closest_prior_invalid": sum(not t["cp_valid"] for t in trials)},
        "all": _measures(papers, trials), "ci95": ci,
        "holdout": _measures([p for p in papers if p["holdout"]], [t for t in trials if t["holdout"]]),
        "levels": {"argon": dict(Counter(t["argon_level"] for t in trials)), "ours": dict(Counter(t["our_level"] for t in trials)),
                   "pairs": dict(Counter(f"{t['our_level']} / {t['argon_level']}" for t in trials))},
        "by_population": {pp: _share([p["found"] for p in papers if p["pop"] == pp]) for pp in ("exact", "adjacent", "other_species")},
        "returned_per_trial_median": sorted(t["n_returned"] for t in trials)[len(trials) // 2],
        "trials": trials,
        "papers": papers,
    }
    (DIR / "bench_search_score.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return {k: v for k, v in out.items() if k not in ("trials", "papers")}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "score"
    print(json.dumps({"check": check, "described": described, "score": score}[cmd](), indent=1, ensure_ascii=False))

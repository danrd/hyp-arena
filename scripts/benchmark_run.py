"""Benchmark v2 (specs/benchmark-v2.yaml), the free part: hypothesis texts, the formal baseline and a dry run with the cost.

    python -m scripts.benchmark_run texts       # $KG_DIR/hypothesis_sources/benchmark_v2_texts.jsonl (private: registry texts)
    python -m scripts.benchmark_run features    # data/benchmark/v2_features.json (registry header fields; no texts)
    python -m scripts.benchmark_run baseline    # formal baseline: 5-fold cross-validated logistic regression, AUC with CI
    python -m scripts.benchmark_run dry         # the pipeline with the fake LLM on every unit: calls per role, cost estimate

Texts are written by code from the registry text only (title, interventions, conditions, summary / description / study
hypothesis, registered primary outcomes): no results, no papers, no registry id, no dates. The date a unit is evaluated "as of"
is its registration date (`written_on`), so evidence published later is cut. Labels are read only by `baseline`.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
import numpy as np
import yaml

from scripts.ctgov_outcomes import KG

HS = KG / "hypothesis_sources"
ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "data" / "benchmark" / "v2_units.json"
TEXTS = HS / "benchmark_v2_texts.jsonl"
FEATURES = ROOT / "data" / "benchmark" / "v2_features.json"
CTGOV = "https://clinicaltrials.gov/api/v2/studies/{}?fields=protocolSection"
CAND = {"ctgov": "ctgov_candidates.yaml", "ctgov_2023": "ctgov_candidates_2023.yaml", "isrctn": "isrctn_candidates.yaml",
        "drks": "drks_candidates.yaml", "ntr": "ntr_candidates.yaml", "anzctr": "anzctr_candidates.yaml"}
MAX_FIELD = 3000                 # characters per free-text field (long CT.gov descriptions); recorded in the text as "[...]"
# words that would mean the registry text reports a result (the record is the current version)
RESULT_WORDS = re.compile(r"\b(results? (showed|show|indicate)|was significantly|were significantly|p\s*[<=]\s*0\.\d|we found|"
                          r"has been completed and)\b", re.I)
# USD per million tokens, CometAPI list prices (catalog 2026-10-29; deepseek doubles 01-04 and 06-10 UTC on weekdays)
PRICES = {"gemini-3.5-flash": (1.5, 9.0), "deepseek-v4.1-flash-1017": (0.15, 0.6), "gpt-4o": (2.5, 10.0)}


def _units() -> list[dict]:
    return json.loads(UNITS.read_text())["units"]


def _list(v) -> list:
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.startswith("["):
        try:
            return ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return [v]
    return [v] if v else []


def _clip(s: str) -> str:
    s = re.sub(r"\s+", " ", re.sub(r"</?\w+>", " ", str(s or ""))).strip()
    return s if len(s) <= MAX_FIELD else s[:MAX_FIELD].rsplit(" ", 1)[0] + " [...]"


def _get(url: str) -> dict:
    for i in range(4):
        try:
            r = httpx.get(url, timeout=60)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            time.sleep(2 ** i)
    raise RuntimeError(url)


def _ctgov(nct: str, cache: dict) -> dict:
    if nct not in cache:
        cache[nct] = _get(CTGOV.format(nct))["protocolSection"]
    return cache[nct]


def _text(fields: list[tuple[str, str]]) -> str:
    return "\n".join(f"{k}: {v}" for k, v in fields if v and v.lower() not in ("not provided at time of registration", "no entry"))


def build_texts() -> list[dict]:
    cands = {s: {c["source_id"]: c for c in (yaml.safe_load((HS / f).read_text()) or {}).get("items", [])} for s, f in CAND.items()}
    cache: dict = {}
    out = []
    for u in _units():
        s, c = u["source"], cands[u["source"]].get(u["id"], {})
        if s.startswith("ctgov"):
            p = _ctgov(u["id"], cache)
            d, a, o = p.get("descriptionModule", {}), p.get("armsInterventionsModule", {}), p.get("outcomesModule", {})
            f = [("Title", p["identificationModule"].get("officialTitle") or p["identificationModule"].get("briefTitle")),
                 ("Conditions", "; ".join(p.get("conditionsModule", {}).get("conditions", []))),
                 ("Interventions", "; ".join(f"{i.get('name')} ({i.get('type', '').lower()})" + (f": {_clip(i['description'])}" if i.get("description") else "")
                                             for i in a.get("interventions", []))),
                 ("Summary", _clip(d.get("briefSummary"))), ("Description", _clip(d.get("detailedDescription"))),
                 ("Primary outcomes", "; ".join(_clip(x.get("measure", "") + (f" ({x['timeFrame']})" if x.get("timeFrame") else ""))
                                               for x in o.get("primaryOutcomes", [])))]
        elif s == "isrctn":
            f = [("Title", c.get("title")), ("Conditions", "; ".join(map(str, _list(c.get("conditions"))))),
                 ("Interventions", "; ".join(_clip(i.get("name") if isinstance(i, dict) else i) for i in _list(c.get("interventions")))),
                 ("Study hypothesis", _clip(c.get("study_hypothesis"))), ("Summary", _clip(c.get("summary"))),
                 ("Primary outcomes", "; ".join(_clip(x.get("measure") if isinstance(x, dict) else x) for x in _list(c.get("primary_outcomes"))))]
        elif s == "drks":
            f = [("Conditions", _clip(c.get("conditions", "").replace(" | ", "; "))), ("Interventions", _clip(c.get("arms", "").replace(" | ", " "))),
                 ("Summary", _clip(c.get("summary"))), ("Primary outcomes", _clip(c.get("primary_outcome")))]
        else:                                                              # ntr, anzctr
            po = re.sub(r"^\d+\s+\d+\s+", "", str(c.get("primary_outcome", "")))
            f = [("Title", c.get("title")), ("Conditions", "; ".join(map(str, _list(c.get("conditions"))))),
                 ("Interventions", _clip(c.get("intervention"))), ("Summary", _clip(c.get("summary"))), ("Primary outcomes", _clip(po))]
        text = "A trial registered to test the following.\n" + _text([(k, str(v)) for k, v in f])
        out.append({"id": u["id"], "as_of": u["written_on"], "b2_clean": u["b2_clean"], "text": text,
                    "result_words": sorted({m.group(0).lower() for m in RESULT_WORDS.finditer(text)})})
    TEXTS.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out))
    (ROOT / "data" / "cache").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "cache" / "ctgov_protocols.json").write_text(json.dumps(cache))
    return out


# --- formal baseline -------------------------------------------------------------------------------------------------------
PHASES = ["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"]
CLASSES = ["NIH", "FED", "INDUSTRY", "OTHER"]
ITYPES = ["DRUG", "DIETARY_SUPPLEMENT", "BEHAVIORAL", "DEVICE", "OTHER"]


def build_features() -> list[dict]:
    """Registry header fields per unit. CT.gov: current record (the first version is not reachable through the public API, so
    the enrolment is the actual one for completed trials). Other registries: the fields this project parsed; missing = None."""
    cache_p = ROOT / "data" / "cache" / "ctgov_protocols.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    cands = {s: {c["source_id"]: c for c in (yaml.safe_load((HS / f).read_text()) or {}).get("items", [])} for s, f in CAND.items()}
    out = []
    for u in _units():
        r = {"id": u["id"], "source": u["source"], "year": int(u["written_on"][:4])}
        if u["source"].startswith("ctgov"):
            p = _ctgov(u["id"], cache)
            d = p.get("designModule", {})
            mask = ((d.get("designInfo") or {}).get("maskingInfo") or {}).get("masking")
            r.update(enrolment=(d.get("enrollmentInfo") or {}).get("count"), phase=max([PHASES.index(x) + 1 for x in d.get("phases", []) if x in PHASES], default=0),
                     randomized=((d.get("designInfo") or {}).get("allocation") == "RANDOMIZED"),
                     masked=None if mask is None else mask not in ("NONE",),
                     itype=[i.get("type") for i in p.get("armsInterventionsModule", {}).get("interventions", [])],
                     n_primary=len(p.get("outcomesModule", {}).get("primaryOutcomes", [])),
                     sponsor=(p.get("sponsorCollaboratorsModule", {}).get("leadSponsor") or {}).get("class"))
        else:
            c = cands[u["source"]].get(u["id"], {})
            r.update(enrolment=None, phase=None, randomized=None, masked=None, itype=[], n_primary=None, sponsor=None,
                     n_primary_text=len(_list(c.get("primary_outcomes"))) if u["source"] == "isrctn" else None)
        out.append(r)
    cache_p.write_text(json.dumps(cache))
    FEATURES.write_text(json.dumps({"benchmark": "v2", "units": out}, indent=1) + "\n")
    return out


def design(rows: list[dict]) -> tuple[np.ndarray, list[str]]:
    """Numeric design matrix; a missing value gets the column median and a missing indicator (one per field group)."""
    cols, X = [], []
    def num(v, med): return med if v is None else float(v)
    enr = [math.log1p(r["enrolment"]) for r in rows if r.get("enrolment") is not None]
    med_e = float(np.median(enr)) if enr else 0.0
    npr = [r["n_primary"] for r in rows if r.get("n_primary") is not None]
    med_n = float(np.median(npr)) if npr else 1.0
    for r in rows:
        miss = r.get("phase") is None
        x = [num(None if r.get("enrolment") is None else math.log1p(r["enrolment"]), med_e),
             0.0 if miss else float(r["phase"]),
             float(bool(r.get("randomized"))), float(bool(r.get("masked"))),
             min(num(r.get("n_primary"), med_n), 5.0),
             (r["year"] - 2010) / 10.0, float(miss)]
        x += [float(t in (r.get("itype") or [])) for t in ITYPES]
        x += [float(r.get("sponsor") == s) for s in CLASSES]
        X.append(x)
    cols = ["log_enrolment", "phase", "randomized", "masked", "n_primary", "year", "not_ctgov"] + [f"itype_{t}" for t in ITYPES] + [f"sponsor_{s}" for s in CLASSES]
    return np.array(X), cols


def logreg(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> np.ndarray:
    """L2-penalised logistic regression by Newton steps (intercept unpenalised). Columns are standardised by the caller."""
    Xb = np.hstack([np.ones((len(X), 1)), X])
    w = np.zeros(Xb.shape[1])
    P = np.eye(Xb.shape[1]) * l2
    P[0, 0] = 0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xb @ w))
        g = Xb.T @ (p - y) + P @ w
        H = Xb.T @ (Xb * (p * (1 - p))[:, None]) + P
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def cv_scores(X: np.ndarray, y: np.ndarray, k: int = 5, seed: int = 0) -> np.ndarray:
    """Out-of-fold scores, folds stratified by label."""
    rng = random.Random(seed)
    folds = np.zeros(len(y), int)
    for lab in (0, 1):
        idx = [i for i in range(len(y)) if y[i] == lab]
        rng.shuffle(idx)
        for j, i in enumerate(idx):
            folds[i] = j % k
    s = np.zeros(len(y))
    for f in range(k):
        tr, te = folds != f, folds == f
        mu, sd = X[tr].mean(0), X[tr].std(0)
        sd[sd == 0] = 1
        w = logreg((X[tr] - mu) / sd, y[tr])
        s[te] = 1 / (1 + np.exp(-(np.hstack([np.ones((te.sum(), 1)), (X[te] - mu) / sd]) @ w)))
    return s


def auc(pos, neg) -> float:
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def baseline(units: list[dict] | None = None) -> dict:
    from hyparena.backtest import bootstrap_auc
    units = units or _units()
    feats = {r["id"]: r for r in json.loads(FEATURES.read_text())["units"]}
    out = {}
    for name, sel in (("B1", units), ("B2", [u for u in units if u["b2_clean"]])):
        rows = [feats[u["id"]] for u in sel]
        y = np.array([u["label"] for u in sel], float)
        X, cols = design(rows)
        s = cv_scores(X, y)
        pos, neg = [float(v) for v, l in zip(s, y) if l == 1], [float(v) for v, l in zip(s, y) if l == 0]
        lo, hi = bootstrap_auc(pos, neg)
        mu, sd = X.mean(0), X.std(0)
        sd[sd == 0] = 1
        w = logreg((X - mu) / sd, y)
        out[name] = {"n": len(y), "positives": int(y.sum()), "auc_cv": round(auc(pos, neg), 3), "ci95": [round(lo, 3), round(hi, 3)],
                     "coef_full_fit": {c: round(float(v), 3) for c, v in zip(cols, w[1:])},
                     "scores": {u["id"]: round(float(v), 4) for u, v in zip(sel, s)}}
    return out


# --- dry run ---------------------------------------------------------------------------------------------------------------
def dry(limit: int | None = None, config: str = "configs/v2-flash.yaml") -> dict:
    """The pipeline with the fake LLM on every unit, each as of its own date: counts calls per role and the tokens of the
    prompts actually built (the fake answers are short, so output tokens come from the earlier paid run, below)."""
    from hyparena.card.pipeline import run as v2
    texts = [json.loads(l) for l in TEXTS.read_text().splitlines()][:limit]
    calls = Counter()
    tin = defaultdict(int)
    per_unit = []
    for t in texts:
        res = v2([t["text"]], writer="human_registry", config=config, fake=True, as_of=t["as_of"], max_calls=60, verifiers=["deepseek"])
        n = Counter()
        for c in res["calls"]:
            if c.get("kind") == "llm":
                calls[c["role"]] += 1
                n[c["role"]] += 1
                tin[c["role"]] += c.get("tokens_in") or 0
        per_unit.append({"id": t["id"], **n})
    return {"units": len(texts), "calls": dict(calls), "tokens_in": dict(tin), "per_unit": per_unit}


def sample(n: int = 20, seed: int = 0, config: str = "configs/v2-gemma31free.yaml") -> dict:
    """A free estimate of the verifier load: real cards from the free Gemma endpoint (registry texts are public, so the free
    endpoint's prompt retention is acceptable) for a random sample of units, then the pipeline with these cards and the fake
    LLM, each as of its own date. The number of claims per card, and so of verifier calls, comes from real cards; the paid
    normalizer may extract a few more or fewer claims."""
    from hyparena.card.normalizer import normalize
    from hyparena.card.pipeline import _client, run as v2
    texts = [json.loads(l) for l in TEXTS.read_text().splitlines()]
    pick = random.Random(seed).sample(texts, n)
    client, fams = _client(config, False, 4 * n)
    rows = []
    for i, t in enumerate(pick, 1):
        log: list = []
        card, problems = normalize(client, fams[0], t["text"], f"H-{i:04d}", log=log)
        norm = [c for c in log if c.get("kind") == "llm"]
        row = {"id": t["id"], "card": bool(card), "claims": len(card.claims) if card else 0, "problems": problems,
               "norm_calls": len(norm), "norm_in": sum(c.get("tokens_in") or 0 for c in norm), "norm_out": sum(c.get("tokens_out") or 0 for c in norm)}
        if card:
            res = v2([t["text"]], writer="human_registry", config="configs/v2-flash.yaml", fake=True, as_of=t["as_of"], max_calls=60,
                     verifiers=["deepseek"], cards=[card.model_dump(by_alias=True)])
            ll = [c for c in res["calls"] if c.get("kind") == "llm"]
            row.update(outcome=res["items"][0]["outcome"], calls=dict(Counter(c["role"] for c in ll)),
                       ver_in=sum(c.get("tokens_in") or 0 for c in ll), searches=sum(c.get("kind") == "search" for c in res["calls"]))
        rows.append(row)
        print(json.dumps(row), flush=True)
    return {"n": n, "seed": seed, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["texts", "features", "baseline", "dry", "sample"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.cmd == "sample":
        r = sample(a.limit or 20)
        if a.out:
            Path(a.out).write_text(json.dumps(r, indent=1) + "\n")
        return
    if a.cmd == "texts":
        t = build_texts()
        L = [len(x["text"]) for x in t]
        print(f"{len(t)} texts, chars median {int(np.median(L))} max {max(L)}; with result words: {sum(bool(x['result_words']) for x in t)}")
        for x in t:
            if x["result_words"]:
                print(" ", x["id"], x["result_words"])
    elif a.cmd == "features":
        f = build_features()
        print(f"{len(f)} units; CT.gov fields for {sum(r['phase'] is not None for r in f)}")
    elif a.cmd == "baseline":
        r = baseline()
        for k, v in r.items():
            print(k, {x: v[x] for x in ("n", "positives", "auc_cv", "ci95")})
        if a.out:
            Path(a.out).write_text(json.dumps(r, indent=1) + "\n")
    else:
        r = dry(a.limit)
        print(json.dumps({k: v for k, v in r.items() if k != "per_unit"}, indent=1))
        if a.out:
            Path(a.out).write_text(json.dumps(r, indent=1) + "\n")


if __name__ == "__main__":
    main()

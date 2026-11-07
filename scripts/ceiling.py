"""Ceiling analysis of the trial-outcome label (free, no model calls): do features of the trial's design, read from the
ClinicalTrials.gov record, order positive and null trials better than P? If they do and P adds little to them, a low AUC of
P is a property of the label (what makes a trial "positive"), not only of the method.

    python -m scripts.ceiling        # writes $KG_DIR/hypothesis_sources/calibration/ceiling.json

Exploration only: the calibration samples were used to build the method. Enrollment is the registry's current value (actual
after completion), so it is known only after the trial: a ceiling feature, not a usable predictor.
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
from pathlib import Path

import numpy as np

from hyparena.backtest import tied_auc
from scripts.ctgov_outcomes import KG

CAL = KG / "hypothesis_sources" / "calibration"
CACHE = Path(__file__).resolve().parents[1] / "data" / "cache" / "ctgov_design.json"
MASK = {"NONE": 0, "SINGLE": 1, "DOUBLE": 2, "TRIPLE": 3, "QUADRUPLE": 4}
ENDPOINT = {"biomarker": 0, "patient_reported": 1, "function": 2, "clinical_event": 3}


def design(nct: str) -> dict:
    c = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if nct not in c:
        url = (f"https://clinicaltrials.gov/api/v2/studies/{nct}?fields=DesignModule,ArmsInterventionsModule,"
               f"SponsorCollaboratorsModule,OutcomesModule")
        for k in range(4):
            try:
                c[nct] = json.load(urllib.request.urlopen(url, timeout=60)).get("protocolSection", {})
                break
            except Exception:
                time.sleep(2 ** k)
        else:
            c[nct] = {}
        CACHE.write_text(json.dumps(c))
    return c[nct]


def features(p: dict) -> dict:
    d = p.get("designModule", {})
    di = d.get("designInfo", {})
    arms = p.get("armsInterventionsModule", {}).get("armGroups", [])
    types = {a.get("type") for a in arms}
    enr = (d.get("enrollmentInfo") or {}).get("count")
    return {
        "randomised": None if not di else float(di.get("allocation") == "RANDOMIZED"),
        "masking": None if not di.get("maskingInfo") else float(MASK.get(di["maskingInfo"].get("masking"), 0)),
        "placebo_or_sham": None if not arms else float(bool(types & {"PLACEBO_COMPARATOR", "SHAM_COMPARATOR"})),
        "single_arm": None if not arms else float(len(arms) == 1),
        "log_enrollment": math.log(enr) if enr else None,
        "industry": float(p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("class") == "INDUSTRY") if p else None,
        "n_primary_outcomes": float(len(p.get("outcomesModule", {}).get("primaryOutcomes", []))) if p else None,
    }


def endpoint(h: str) -> float | None:
    d = json.loads((CAL / "estimand_v1.json").read_text())
    v = {(d.get(f"{h}|{f}") or {}).get("clean", {}).get("endpoint") for f in ("google", "deepseek")}
    v = v.pop() if len(v) == 1 else None
    return float(ENDPOINT[v]) if v in ENDPOINT else None


def auc(rows, key, sign=1.0):
    pts = [(sign * r[key], r["label"]) for r in rows if r.get(key) is not None]
    pos, neg = [(v, 0) for v, l in pts if l == 1], [(v, 0) for v, l in pts if l == 0]
    return (round(tied_auc(pos, neg), 3), len(pts)) if pos and neg else None


def logit_cv(rows, keys, l2: float = 1.0, folds: int = 5, reps: int = 40) -> tuple[float, int] | None:
    """Mean AUC of an L2 logistic regression on `keys` over repeated stratified 5-fold cross-validation (leave-one-out is
    biased below 0.5 for weak signals); missing values set to the training mean, standardised on the training part."""
    Xr = np.array([[r.get(k) if r.get(k) is not None else np.nan for k in keys] for r in rows], float)
    y = np.array([r["label"] for r in rows], float)

    def fit(A, b):
        w = np.zeros(A.shape[1])
        for _ in range(50):
            p = 1 / (1 + np.exp(-A @ w))
            g = A.T @ (p - b) + l2 * np.r_[0, w[1:]]
            H = A.T @ (A * (p * (1 - p))[:, None]) + l2 * np.diag(np.r_[0, np.ones(len(w) - 1)])
            w -= np.linalg.solve(H, g)
        return w

    def prep(Xtr, Xte):
        mu = np.nanmean(Xtr, 0)
        mu = np.where(np.isnan(mu), 0, mu)
        Xtr, Xte = np.where(np.isnan(Xtr), mu, Xtr), np.where(np.isnan(Xte), mu, Xte)
        sd = Xtr.std(0)
        sd[sd == 0] = 1
        f = lambda X: np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
        return f(Xtr), f(Xte)
    rng = np.random.default_rng(0)
    aucs = []
    pos_i, neg_i = np.where(y == 1)[0], np.where(y == 0)[0]
    for _ in range(reps):
        fp, fn = np.array_split(rng.permutation(pos_i), folds), np.array_split(rng.permutation(neg_i), folds)
        for k in range(folds):
            te = np.r_[fp[k], fn[k]]
            tr = np.setdiff1d(np.arange(len(y)), te)
            A, B = prep(Xr[tr], Xr[te])
            s = B @ fit(A, y[tr])
            pos, neg = [(v, 0) for v, l in zip(s, y[te]) if l == 1], [(v, 0) for v, l in zip(s, y[te]) if l == 0]
            if pos and neg:
                aucs.append(tied_auc(pos, neg))
    return round(float(np.mean(aucs)), 3), len(y)


def main() -> dict:
    v34 = {r["id"]: r for r in json.loads((CAL / "v34_check.json").read_text())["rows"] if r["sample"].startswith("calibration")}
    ea = {r["id"]: r for r in json.loads((CAL / "error_analysis_v33.json").read_text())["rows"]}
    rows = []
    for h, r in v34.items():
        if r["label"] not in (0, 1) or r["gate"] != "pass":
            continue
        row = {"id": h, "label": r["label"], "P34": r["P34"], "support_share": r["ss34"], "I": r["I"],
               "S_outcome": (ea.get(h) or {}).get("S_outcome"), "N": r["N"], "endpoint": endpoint(h),
               "lit_volume": (lambda v: math.log(v) if v else None)((ea.get(h) or {}).get("lit_volume"))}
        if h.startswith("NCT"):
            row.update(features(design(h)))
        rows.append(row)
    keys = ["P34", "support_share", "S_outcome", "I", "endpoint", "lit_volume", "randomised", "masking", "placebo_or_sham",
            "single_arm", "log_enrollment", "industry", "n_primary_outcomes"]
    out = {"n": len(rows), "positives": sum(r["label"] for r in rows),
           "single": {k: auc(rows, k) for k in keys},
           "nct_rows": sum(1 for r in rows if r["id"].startswith("NCT"))}
    design_pre = ["randomised", "masking", "placebo_or_sham", "single_arm", "industry", "n_primary_outcomes", "endpoint"]
    out["models_cv"] = {
        "P alone": logit_cv(rows, ["P34"]),
        "outcome link alone": logit_cv(rows, ["S_outcome"]),
        "design known before the trial": logit_cv(rows, design_pre),
        "design + P": logit_cv(rows, design_pre + ["P34"]),
        "design + outcome link": logit_cv(rows, design_pre + ["S_outcome"]),
        "design + enrollment (ceiling, enrollment known after)": logit_cv(rows, design_pre + ["log_enrollment"]),
    }
    (CAL / "ceiling.json").write_text(json.dumps({"summary": out, "rows": rows}, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

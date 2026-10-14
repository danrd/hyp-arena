"""Backtest harness: build a labelled pool "as of date T" and evaluate a run against hidden labels.

    python -m hyparena.backtest build-itp --as-of 2010-12-31     # data/backtest/itp_<T>.json + _labels.json
    python -m hyparena.live run --import-file data/backtest/itp_<T>.json --as-of <T> --out runs/r.json
    python -m hyparena.backtest evaluate --labels data/backtest/itp_<T>_labels.json --result runs/r.json

ITP pool: interventions tested by the NIA Interventions Testing Program, taken from DrugAge (HAGR, CC BY
3.0; rows flagged ITP). A compound enters the pool if its first ITP publication in DrugAge is after T; its
label is 1 if any ITP row reports a significant increase of average lifespan, else 0. The hypothesis text
states the intervention and the claimed effect, not the outcome. Labels go to a separate file that the
pipeline never reads; metrics are computed here, outside the graph (hidden evaluation).

Caveat, important: models trained after T may know ITP outcomes. With current models this measures
recall of known results as much as judgement. Use judges whose training cutoff precedes T, or treat the
numbers as an upper bound."""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import zipfile
from collections import defaultdict
from pathlib import Path

import httpx

DRUGAGE_URL = "https://genomics.senescence.info/drugs/dataset.zip"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
OUT = Path(__file__).resolve().parents[1] / "data" / "backtest"


def _pubdates(pmids: list[str]) -> dict[str, str]:
    """PubMed id -> ISO publication date (sortpubdate), via NCBI E-utilities (batches of 150)."""
    dates = {}
    with httpx.Client(timeout=60) as client:
        for i in range(0, len(pmids), 150):
            batch = pmids[i:i + 150]
            r = client.get(ESUMMARY, params={"db": "pubmed", "id": ",".join(batch), "retmode": "json"})
            r.raise_for_status()
            res = r.json().get("result", {})
            for p in batch:
                sort = (res.get(p) or {}).get("sortpubdate", "")
                if sort:
                    dates[p] = sort[:10].replace("/", "-")
    return dates


def build_itp(as_of: str) -> tuple[Path, Path]:
    raw = httpx.get(DRUGAGE_URL, timeout=120, follow_redirects=True).content
    z = zipfile.ZipFile(io.BytesIO(raw))
    rows = list(csv.DictReader(io.TextIOWrapper(z.open("drugage.csv"), encoding="utf-8", errors="replace")))
    itp = [r for r in rows if r.get("ITP", "").strip().lower() == "yes"]
    by_compound = defaultdict(list)
    for r in itp:
        by_compound[r["compound_name"].strip()].append(r)
    dates = _pubdates(sorted({r["pubmed_id"] for r in itp if r["pubmed_id"].strip()}))
    items, labels = [], {}
    for n, (compound, rs) in enumerate(sorted(by_compound.items()), start=1):
        pub = sorted(dates[r["pubmed_id"]] for r in rs if r["pubmed_id"] in dates)
        if not pub or pub[0] <= as_of:
            continue
        def pct(v):
            try:
                return float(v)
            except ValueError:
                return 0.0
        positive = any(r["avg_lifespan_significance"].strip() == "S" and pct(r["avg_lifespan_change_percent"]) > 0 for r in rs)
        hid = len(items) + 1
        items.append({"id": hid, "title": f"{compound} extends lifespan in genetically heterogeneous mice",
                      "claim": (f"Chronic dietary administration of {compound}, started in adulthood, increases the "
                                f"median lifespan of genetically heterogeneous UM-HET3 mice of at least one sex."),
                      "message": 0})
        labels[f"imp{hid:03d}"] = {"label": int(positive), "compound": compound, "first_itp_publication": pub[0],
                                   "pmids": sorted({r["pubmed_id"] for r in rs})}
    OUT.mkdir(parents=True, exist_ok=True)
    data_path, label_path = OUT / f"itp_{as_of}.json", OUT / f"itp_{as_of}_labels.json"
    data_path.write_text(json.dumps({"source": {"url": DRUGAGE_URL, "family": "unknown", "model": "backtest-template",
                                                "as_of": as_of, "note": "outcome labels are in a separate file",
                                                "options": {"dedup": False}},
                                     "hypotheses": items, "assistant_notes": {}}, ensure_ascii=False, indent=2))
    label_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2))
    pos = sum(v["label"] for v in labels.values())
    print(f"ITP compounds in DrugAge: {len(by_compound)}; first ITP publication after {as_of}: {len(items)} "
          f"({pos} positive, {len(items) - pos} negative)\n{data_path}\n{label_path}")
    return data_path, label_path


def auc(pos: list[float], neg: list[float]) -> float:
    """Probability that a positive outranks a negative (ties count half)."""
    if not pos or not neg:
        return float("nan")
    wins = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def bootstrap_auc(pos: list[float], neg: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    vals = sorted(auc([rng.choice(pos) for _ in pos], [rng.choice(neg) for _ in neg]) for _ in range(n))
    return vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


def evaluate(labels_path: str, result_path: str) -> dict:
    labels = json.loads(Path(labels_path).read_text())
    result = json.loads(Path(result_path).read_text())
    hyps = result["hypotheses"]
    out = {"n_labelled": len(labels), "status_by_label": defaultdict(lambda: defaultdict(int)), "metrics": {}}
    for hid, lab in labels.items():
        out["status_by_label"][lab["label"]][hyps.get(hid, {}).get("status", "missing")] += 1
    rated = {hid: h for hid, h in hyps.items() if hid in labels and h.get("combined") is not None}
    for key in ["combined"] + list(result.get("criteria", [])):
        get = (lambda h: h["combined"]) if key == "combined" else (lambda h, k=key: h["scores"][k]["score"])
        pos = [get(h) for hid, h in rated.items() if labels[hid]["label"] == 1]
        neg = [get(h) for hid, h in rated.items() if labels[hid]["label"] == 0]
        lo, hi = bootstrap_auc(pos, neg) if pos and neg else (float("nan"), float("nan"))
        out["metrics"][key] = {"auc": auc(pos, neg), "auc_95ci": [lo, hi], "n_pos": len(pos), "n_neg": len(neg)}
    order = sorted(rated, key=lambda hid: -rated[hid]["combined"])
    k = max(1, len(order) // 4)
    out["precision_at_top_quarter"] = sum(labels[h]["label"] for h in order[:k]) / k if order else float("nan")
    out["base_rate"] = sum(v["label"] for v in labels.values()) / len(labels) if labels else float("nan")
    out["status_by_label"] = {str(k): dict(v) for k, v in out["status_by_label"].items()}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-itp")
    b.add_argument("--as-of", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--labels", required=True)
    e.add_argument("--result", required=True)
    args = ap.parse_args()
    if args.cmd == "build-itp":
        build_itp(args.as_of)
    else:
        print(json.dumps(evaluate(args.labels, args.result), indent=2))


if __name__ == "__main__":
    main()

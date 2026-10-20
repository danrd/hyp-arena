"""Backtest pools from curated program outcomes (Working_Notes A2, decided 2026-10-20).

Pool: ITP and CITP compound tests whose result became public after T (data/backtest/outcomes_itp_citp.yaml for
T after 2022; DrugAge's ITP rows for earlier T, hyparena.backtest build-itp). One templated hypothesis per test;
a repeat at another dose or start age is its own hypothesis. Evidence for the system is restricted to papers
published by T. Labels (supports / no effect / harmful, effect size and sex apart) are in a separate file the
pipeline never reads.

Two sets: `clean` (results public after the cutoff of every model used, for comparisons with baselines) and
`historical` (models may know the results: for our system only, whose evidence is cut at T). Models are chosen
by cutoff <= T (configs/model_cutoffs.yaml; heuristic cutoff = release date - 6 months). The leakage probe is
not used.

Metrics: AUC (supports vs the rest), Spearman correlation of the score with the effect size, precision@k, and
calibration of the pairwise P(A > B) against the ordered labels (supports > no effect > harmful).

    python -m hyparena.outcomes check                      # quotes verbatim in the abstracts, public dates
    python -m hyparena.outcomes build --as-of 2025-06-30   # data/backtest/outcomes_<T>.json + _labels.json
    python -m hyparena.outcomes models --as-of 2025-06-30  # which models may judge as of T
    python -m hyparena.outcomes metrics --labels ... --v2 runs/x.json --profile evidence_first"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUTCOMES = ROOT / "data" / "backtest" / "outcomes_itp_citp.yaml"
CUTOFFS = ROOT / "configs" / "model_cutoffs.yaml"
OUT = ROOT / "data" / "backtest"
ORDER = {"harmful": 0, "no_effect": 1, "supports": 2}


# ---- the curated tests ----

def load_tests(path: Path = OUTCOMES) -> list[dict]:
    """Tests with `quote_ref` resolved to the quote of the referenced test."""
    tests = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["tests"]
    by_id = {t["id"]: t for t in tests}
    for t in tests:
        if "quote" not in t and t.get("quote_ref"):
            t["quote"] = by_id[t["quote_ref"]]["quote"]
    return tests


def check(path: Path = OUTCOMES) -> list[str]:
    """Problems: a quote not verbatim in its abstract, a public date later than PubMed's, duplicate ids."""
    from hyparena.backtest import _pubdates
    from hyparena.tools import pubmed
    tests = load_tests(path)
    problems = [f"duplicate id {i}" for i in {t["id"] for t in tests} if sum(x["id"] == i for x in tests) > 1]
    pmids = sorted({t["pmid"] for t in tests})
    abstracts, dates = pubmed.fetch(pmids), _pubdates(pmids)
    norm = lambda s: " ".join((s or "").split()).lower()
    for t in tests:
        a = abstracts.get(t["pmid"])
        if a is None:
            problems.append(f"{t['id']}: PMID {t['pmid']} not fetched")
        elif norm(t["quote"]) not in norm(a["title"] + " " + a["abstract"]):
            problems.append(f"{t['id']}: quote not verbatim in PMID {t['pmid']}")
        if t["pmid"] in dates and t.get("date_precision") != "year" and not t.get("date_source") \
                and t["public_date"] > dates[t["pmid"]]:
            problems.append(f"{t['id']}: public date {t['public_date']} after PubMed's {dates[t['pmid']]}")
        if t["label"] not in ORDER:
            problems.append(f"{t['id']}: label {t['label']}")
    return problems


def effect(t: dict) -> Optional[float]:
    """Effect size for the rank correlation: the largest stated change of median lifespan in either sex; 0 for
    a stated null result without a number; None when a positive or harmful result has no number."""
    sizes = list((t.get("effect_percent") or {}).values())
    if t["label"] == "supports":
        return max(sizes) if sizes else None
    if t["label"] == "harmful":
        return min(sizes) if sizes else None
    return 0.0


def after(t: dict, as_of: str) -> bool:
    """Public after T; a date known only to the year counts only when the year is after T's year."""
    if t.get("date_precision") == "year":
        return t["public_date"][:4] > as_of[:4]
    return t["public_date"] > as_of


def phrasable(t: dict) -> bool:
    """A repeat needs its own regimen in the text; repeats whose dose and start age the abstract does not give
    are kept in the file but left out of pools."""
    return not t.get("repeat_of") or bool(t.get("dose") or t.get("age_at_start"))


def text(t: dict) -> str:
    """The templated hypothesis: intervention, regimen as far as known, the claimed effect; never the result."""
    regimen = ", ".join(x for x in (f"at {t['dose']}" if t.get("dose") else "",
                                    f"started at {t['age_at_start']}" if t.get("age_at_start") else "") if x)
    regimen = f" ({regimen})" if regimen else ""
    if t["species"] == "mouse":
        return (f"Dietary {t['compound']}{regimen} extends the median lifespan of genetically heterogeneous "
                f"UM-HET3 mice of at least one sex.")
    return (f"{t['compound'][0].upper()}{t['compound'][1:]}{regimen} extends the lifespan of Caenorhabditis "
            f"nematodes across genetically diverse species and strains.")


# ---- model cutoffs ----

def _months_before(date: str, months: int) -> str:
    d = dt.date.fromisoformat(date)
    y, m = divmod(d.month - 1 - months, 12)
    return dt.date(d.year + y, m + 1, min(d.day, 28)).isoformat()


def cutoffs(path: Path = CUTOFFS) -> dict[str, str]:
    """Model id -> training cutoff: stated, else release date minus the heuristic months."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    months = int(data.get("heuristic_months", 6))
    return {m: v.get("cutoff") or _months_before(v["released"], months)
            for m, v in (data.get("models") or {}).items() if v.get("cutoff") or v.get("released")}


def eligible(as_of: str, models: Optional[list[str]] = None) -> dict[str, bool]:
    """Which models may judge a pool as of T (cutoff <= T); a model without a known cutoff may not."""
    cut = cutoffs()
    return {m: (m in cut and cut[m] <= as_of) for m in (models or sorted(cut))}


# ---- pools ----

def build(as_of: str, clean_after: Optional[str] = None, path: Path = OUTCOMES) -> tuple[Path, Path]:
    """Pool and labels for T = `as_of`: tests public after T. `clean_after`: the latest cutoff of the models
    to compare (default T); a test is `clean` when it became public after it, else `historical`."""
    from hyparena.backtest import assign_splits
    clean_after = clean_after or as_of
    tests = [t for t in load_tests(path) if after(t, as_of) and phrasable(t)]
    items, labels = [], {}
    for n, t in enumerate(tests, start=1):
        items.append({"id": n, "title": text(t), "claim": text(t), "message": 0})
        labels[f"imp{n:03d}"] = {
            "label": int(t["label"] == "supports"), "outcome": t["label"], "effect": effect(t),
            "by_sex": t.get("by_sex", {}), "compound": t["compound"], "test": t["id"], "program": t["program"],
            "species": t["species"], "pmid": t["pmid"], "public_date": t["public_date"],
            "set": "clean" if after(t, clean_after) else "historical", "repeat_of": t.get("repeat_of", "")}
    assign_splits(labels)
    OUT.mkdir(parents=True, exist_ok=True)
    data_path, label_path = OUT / f"outcomes_{as_of}.json", OUT / f"outcomes_{as_of}_labels.json"
    data_path.write_text(json.dumps({"source": {"url": str(path.relative_to(ROOT)), "family": "unknown",
                                                "model": "backtest-template", "as_of": as_of,
                                                "note": "outcome labels are in a separate file",
                                                "options": {"dedup": False, "lang": "en"}},
                                     "hypotheses": items, "assistant_notes": {}}, ensure_ascii=False, indent=2))
    label_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2))
    return data_path, label_path


def counts(as_of_dates: list[str], path: Path = OUTCOMES) -> list[dict]:
    """Size of the pool (and its positives) for several T."""
    tests = [t for t in load_tests(path) if phrasable(t)]
    return [{"as_of": d, "tests": sum(after(t, d) for t in tests),
             "supports": sum(after(t, d) and t["label"] == "supports" for t in tests),
             "itp": sum(after(t, d) and t["program"] == "ITP" for t in tests),
             "citp": sum(after(t, d) and t["program"] == "CITP" for t in tests)} for d in as_of_dates]


# ---- metrics ----

def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    if len(x) < 3:
        return float("nan")
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx, sy = math.sqrt(sum((a - mx) ** 2 for a in rx)), math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (sx * sy) if sx and sy else float("nan")


def calibration(pairwise: dict[str, dict[str, float]], labels: dict[str, dict], bins: int = 5) -> dict:
    """Pairs with different ordered labels: predicted P(A > B) against the observed order. Brier score and a
    reliability table (bins of the predicted probability)."""
    rows = []
    ids = sorted(labels)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            la, lb = ORDER[labels[a]["outcome"]], ORDER[labels[b]["outcome"]]
            p = (pairwise.get(a) or {}).get(b)
            if p is None and (pairwise.get(b) or {}).get(a) is not None:
                p = 1.0 - pairwise[b][a]
            if la == lb or p is None:
                continue
            rows.append((p, 1.0 if la > lb else 0.0))
    if not rows:
        return {"pairs": 0}
    table = []
    for k in range(bins):
        lo, hi = k / bins, (k + 1) / bins
        inside = [(p, o) for p, o in rows if lo <= p < hi or (k == bins - 1 and p == 1.0)]
        if inside:
            table.append({"bin": [lo, hi], "n": len(inside), "predicted": sum(p for p, _ in inside) / len(inside),
                          "observed": sum(o for _, o in inside) / len(inside)})
    return {"pairs": len(rows), "brier": sum((p - o) ** 2 for p, o in rows) / len(rows), "reliability": table}


def scores_v2(res: dict, profile: str) -> dict[str, float]:
    """Score per pool item from a v2 output: the expected value under the profile; filtered hypotheses and
    those not admitted go below every ranked one; a known result (an exact supported finding by T) above."""
    rank = (res.get("ranking") or {}).get(profile) or {}
    expected = rank.get("expected") or {}
    out = {}
    for n, x in enumerate(res["items"], start=1):
        h, cid = f"imp{n:03d}", x["id"]
        if x["outcome"] == "ranked" and cid in expected:
            out[h] = float(expected[cid])
        elif x["outcome"] == "known_result":
            out[h] = float("inf")
        else:
            out[h] = float("-inf")
    return out


def metrics(labels: dict[str, dict], scores: dict[str, float], pairwise: Optional[dict] = None,
            k: Optional[int] = None, subset: str = "all") -> dict:
    """AUC (supports vs the rest), Spearman with the effect size, precision@k, calibration of P(A > B)."""
    from hyparena.backtest import auc, bootstrap_auc
    items = {h: v for h, v in labels.items() if h in scores and (subset == "all" or v.get("set") == subset)}
    pos = [scores[h] for h, v in items.items() if v["outcome"] == "supports"]
    neg = [scores[h] for h, v in items.items() if v["outcome"] != "supports"]
    finite = lambda s: s if math.isfinite(s) else (1e9 if s > 0 else -1e9)
    with_effect = [(finite(scores[h]), v["effect"]) for h, v in items.items() if v.get("effect") is not None]
    order = sorted(items, key=lambda h: -scores[h])
    k = k or max(1, len(order) // 4)
    out = {"subset": subset, "n": len(items), "n_supports": len(pos), "auc": auc(pos, neg),
           "auc_95ci": list(bootstrap_auc(pos, neg)) if pos and neg else [float("nan")] * 2,
           "spearman_effect": spearman([a for a, _ in with_effect], [b for _, b in with_effect]),
           "n_with_effect": len(with_effect), "k": k,
           "precision_at_k": sum(items[h]["outcome"] == "supports" for h in order[:k]) / k if order else float("nan"),
           "base_rate": len(pos) / len(items) if items else float("nan")}
    if pairwise is not None:
        out["calibration"] = calibration(pairwise, items)
    return out


def metrics_v2(labels_path: str, v2_path: str, profile: str = "evidence_first", subset: str = "all") -> dict:
    labels = json.loads(Path(labels_path).read_text())
    res = json.loads(Path(v2_path).read_text())
    by_item = {x["id"]: f"imp{n:03d}" for n, x in enumerate(res["items"], start=1)}
    pw = ((res.get("ranking") or {}).get(profile) or {}).get("pairwise") or {}
    pairwise = {by_item[a]: {by_item[b]: p for b, p in row.items() if b in by_item} for a, row in pw.items() if a in by_item}
    return metrics(labels, scores_v2(res, profile), pairwise, subset=subset)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    b = sub.add_parser("build")
    b.add_argument("--as-of", required=True)
    b.add_argument("--clean-after", default=None, help="latest cutoff of the models compared (default: T)")
    c = sub.add_parser("counts")
    c.add_argument("--as-of", nargs="+", default=["2022-12-31", "2023-12-31", "2024-12-31", "2025-06-30", "2025-11-19"])
    m = sub.add_parser("models")
    m.add_argument("--as-of", required=True)
    e = sub.add_parser("metrics")
    e.add_argument("--labels", required=True)
    e.add_argument("--v2", required=True)
    e.add_argument("--profile", default="evidence_first")
    e.add_argument("--subset", choices=["all", "clean", "historical"], default="all")
    args = ap.parse_args()
    if args.cmd == "check":
        problems = check()
        print("\n".join(problems) or f"ok: {len(load_tests())} tests")
    elif args.cmd == "build":
        print(*build(args.as_of, args.clean_after), sep="\n")
    elif args.cmd == "counts":
        print(json.dumps(counts(args.as_of), indent=1))
    elif args.cmd == "models":
        print(json.dumps({"cutoffs": cutoffs(), "eligible": eligible(args.as_of)}, indent=1))
    else:
        print(json.dumps(metrics_v2(args.labels, args.v2, args.profile, args.subset), indent=2))


if __name__ == "__main__":
    main()

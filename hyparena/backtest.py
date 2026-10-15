"""Backtest harness: build a labelled pool "as of date T" and evaluate a run against hidden labels.

    python -m hyparena.backtest build-itp --as-of 2010-12-31     # data/backtest/itp_<T>.json + _labels.json
    python -m hyparena.live run --import-file data/backtest/itp_<T>.json --as-of <T> --out runs/r.json
    python -m hyparena.backtest evaluate --labels data/backtest/itp_<T>_labels.json --result runs/r.json
    python -m hyparena.backtest compare --labels ... --a runs/exp/L0_*.json --b runs/exp/L4_*.json --split test

Splits: every item is assigned to `dev` (for tuning prompts and weights) or `test` (for the one final
comparison), stratified by label and deterministic (hash of the compound name). Items that a judge model
already knows (hyparena.leakage) can be excluded with --exclude-known.

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
import glob
import hashlib
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


def drugage_rows() -> list[dict]:
    """All rows of the current DrugAge release (downloaded each time; about 0.5 MB)."""
    raw = httpx.get(DRUGAGE_URL, timeout=120, follow_redirects=True).content
    z = zipfile.ZipFile(io.BytesIO(raw))
    return list(csv.DictReader(io.TextIOWrapper(z.open("drugage.csv"), encoding="utf-8", errors="replace")))


def build_itp(as_of: str) -> tuple[Path, Path]:
    rows = drugage_rows()
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
    assign_splits(labels)
    OUT.mkdir(parents=True, exist_ok=True)
    data_path, label_path = OUT / f"itp_{as_of}.json", OUT / f"itp_{as_of}_labels.json"
    data_path.write_text(json.dumps({"source": {"url": DRUGAGE_URL, "family": "unknown", "model": "backtest-template",
                                                "as_of": as_of, "note": "outcome labels are in a separate file",
                                                "options": {"dedup": False, "lang": "en"}},
                                     "hypotheses": items, "assistant_notes": {}}, ensure_ascii=False, indent=2))
    label_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2))
    pos = sum(v["label"] for v in labels.values())
    print(f"ITP compounds in DrugAge: {len(by_compound)}; first ITP publication after {as_of}: {len(items)} "
          f"({pos} positive, {len(items) - pos} negative)\n{data_path}\n{label_path}")
    return data_path, label_path


def assign_splits(labels: dict, test_share: float = 0.5) -> None:
    """Stratified, deterministic dev/test split: within each label, items ordered by a hash of the
    compound name; every 1/test_share-th goes to test."""
    for lab in (0, 1):
        ids = sorted((h for h, v in labels.items() if v["label"] == lab),
                     key=lambda h: hashlib.sha1(labels[h]["compound"].encode()).hexdigest())
        step = max(1, round(1 / test_share))
        for i, h in enumerate(ids):
            labels[h]["split"] = "test" if i % step == 0 else "dev"


def _items(labels: dict, split: str, known: set[str]) -> dict:
    return {h: v for h, v in labels.items()
            if (split == "all" or v.get("split", "test") == split) and h not in known}


def _scores(result: dict, key: str, ids, unrated: str) -> dict[str, float]:
    """Score per item for `key` ("combined" or a criterion). Items without a rating (rejected, merged,
    never compared) go to the bottom with `unrated="bottom"` (a rejection is a ranking decision), or are
    left out with "drop"."""
    out = {}
    for h in ids:
        x = result["hypotheses"].get(h, {})
        if key == "combined":
            s = x.get("combined")
        else:
            s = (x.get("scores", {}).get(key) or {}).get("score")
        if s is None:
            if unrated == "bottom":
                out[h] = float("-inf")
        else:
            out[h] = float(s)
    return out


def _known(path: str | None, families: list[str] | None) -> set[str]:
    if not path:
        return set()
    data = json.loads(Path(path).read_text())["known"]
    return {h for fam, ids in data.items() if not families or fam in families for h in ids}


def kendall_tau(a: dict[str, float], b: dict[str, float]) -> float:
    ids = sorted(set(a) & set(b))
    conc = disc = 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            x = (a[ids[i]] > a[ids[j]]) - (a[ids[i]] < a[ids[j]])
            y = (b[ids[i]] > b[ids[j]]) - (b[ids[i]] < b[ids[j]])
            if x and y:
                conc += x == y
                disc += x != y
    return (conc - disc) / (conc + disc) if conc + disc else float("nan")


def compare(labels_path: str, a_paths: list[str], b_paths: list[str], split: str = "test", unrated: str = "bottom",
            key: str = "combined", known_path: str | None = None, known_families: list[str] | None = None,
            n_boot: int = 2000, seed: int = 0) -> dict:
    """Paired comparison of two arms (each a list of runs, e.g. seeds) on the same items: mean AUC per arm,
    the difference A - B with a paired bootstrap over items (stratified by label), and rank stability
    across the runs of each arm (mean pairwise Kendall tau)."""
    labels = json.loads(Path(labels_path).read_text())
    items = _items(labels, split, _known(known_path, known_families))
    runs = {arm: [json.loads(Path(p).read_text()) for p in paths] for arm, paths in (("A", a_paths), ("B", b_paths))}
    scores = {arm: [_scores(r, key, items, unrated) for r in rs] for arm, rs in runs.items()}
    common = set(items)
    for arm in scores:
        for s in scores[arm]:
            common &= set(s)
    pos = sorted(h for h in common if items[h]["label"] == 1)
    neg = sorted(h for h in common if items[h]["label"] == 0)

    def arm_auc(arm, p, n):
        vals = [auc([s[h] for h in p], [s[h] for h in n]) for s in scores[arm]]
        return sum(vals) / len(vals)

    point = {arm: arm_auc(arm, pos, neg) for arm in scores}
    rng = random.Random(seed)
    diffs, per = [], {"A": [], "B": []}
    for _ in range(n_boot):
        p = [rng.choice(pos) for _ in pos]
        n = [rng.choice(neg) for _ in neg]
        a, bb = arm_auc("A", p, n), arm_auc("B", p, n)
        diffs.append(a - bb)
        per["A"].append(a)
        per["B"].append(bb)
    ci = lambda v: [sorted(v)[int(0.025 * n_boot)], sorted(v)[int(0.975 * n_boot) - 1]]
    stability = {}
    for arm, ss in scores.items():
        taus = [kendall_tau(ss[i], ss[j]) for i in range(len(ss)) for j in range(i + 1, len(ss))]
        stability[arm] = sum(taus) / len(taus) if taus else None
    def spend(r, phases=None):
        return sum(row["tokens_in"] + row["tokens_out"] for ph, row in r.get("tokens", {}).items()
                   if phases is None or ph in phases)
    cost = {arm: {"all_phases": sum(spend(r) for r in rs) / len(rs),
                  "ranking_only": sum(spend(r, {"rank", "debate"}) for r in rs) / len(rs)}
            for arm, rs in runs.items()}
    return {"split": split, "key": key, "unrated": unrated, "n_pos": len(pos), "n_neg": len(neg),
            "excluded_known": len(_known(known_path, known_families) & set(labels)),
            "runs": {arm: len(rs) for arm, rs in runs.items()},
            "steps": {arm: sorted({r.get("step", "") for r in rs}) for arm, rs in runs.items()},
            "auc": {arm: {"mean": point[arm], "ci95": ci(per[arm])} for arm in point},
            "diff_A_minus_B": {"mean": point["A"] - point["B"], "ci95": ci(diffs),
                               "share_of_bootstrap_above_0": sum(d > 0 for d in diffs) / n_boot},
            "rank_stability_kendall_tau": stability, "mean_estimated_tokens_per_run": cost,
            "note": "token counts are estimates (4 characters per token) without hidden reasoning tokens"}


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


def evaluate(labels_path: str, result_path: str, split: str = "all", unrated: str = "bottom",
             known_path: str | None = None, known_families: list[str] | None = None) -> dict:
    """One run against the labels: AUC of the combined score and of each criterion (bootstrap 95% CI),
    precision in the top quarter vs the base rate, and the status of positives and negatives."""
    labels = json.loads(Path(labels_path).read_text())
    items = _items(labels, split, _known(known_path, known_families))
    result = json.loads(Path(result_path).read_text())
    status = defaultdict(lambda: defaultdict(int))
    for h, lab in items.items():
        status[lab["label"]][result["hypotheses"].get(h, {}).get("status", "missing")] += 1
    out = {"split": split, "unrated": unrated, "n_items": len(items), "metrics": {}}
    for key in ["combined"] + list(result.get("criteria", [])):
        s = _scores(result, key, items, unrated)
        pos = [v for h, v in s.items() if items[h]["label"] == 1]
        neg = [v for h, v in s.items() if items[h]["label"] == 0]
        lo, hi = bootstrap_auc(pos, neg) if pos and neg else (float("nan"), float("nan"))
        out["metrics"][key] = {"auc": auc(pos, neg), "auc_95ci": [lo, hi], "n_pos": len(pos), "n_neg": len(neg)}
    comb = _scores(result, "combined", items, unrated)
    order = sorted(comb, key=lambda h: -comb[h])
    k = max(1, len(order) // 4)
    out["precision_at_top_quarter"] = sum(items[h]["label"] for h in order[:k]) / k if order else float("nan")
    out["base_rate"] = sum(v["label"] for v in items.values()) / len(items) if items else float("nan")
    out["status_by_label"] = {str(k): dict(v) for k, v in status.items()}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-itp")
    b.add_argument("--as-of", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--labels", required=True)
    common.add_argument("--split", choices=["dev", "test", "all"], default="all")
    common.add_argument("--unrated", choices=["bottom", "drop"], default="bottom")
    common.add_argument("--exclude-known", default=None, help="known-items file from hyparena.leakage")
    common.add_argument("--known-families", default=None, help="comma-separated families to take into account")
    e = sub.add_parser("evaluate", parents=[common])
    e.add_argument("--result", required=True)
    c = sub.add_parser("compare", parents=[common])
    c.add_argument("--a", nargs="+", required=True, help="result files of arm A (globs allowed)")
    c.add_argument("--b", nargs="+", required=True, help="result files of arm B (globs allowed)")
    c.add_argument("--key", default="combined", help="combined or a criterion name")
    args = ap.parse_args()
    fams = args.known_families.split(",") if getattr(args, "known_families", None) else None
    if args.cmd == "build-itp":
        build_itp(args.as_of)
    elif args.cmd == "evaluate":
        print(json.dumps(evaluate(args.labels, args.result, args.split, args.unrated, args.exclude_known, fams), indent=2))
    else:
        expand = lambda ps: sorted(f for p in ps for f in (glob.glob(p) or [p]))
        print(json.dumps(compare(args.labels, expand(args.a), expand(args.b), args.split, args.unrated, args.key,
                                 args.exclude_known, fams), indent=2))


if __name__ == "__main__":
    main()

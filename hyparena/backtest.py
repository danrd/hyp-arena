"""Backtest harness: build a labelled pool "as of date T" and evaluate a run against hidden labels.

    python -m hyparena.backtest build-itp --as-of 2010-12-31     # data/backtest/itp_<T>.json + _labels.json
    python -m hyparena.live run --import-file data/backtest/itp_<T>.json --as-of <T> --out runs/r.json
    python -m hyparena.backtest evaluate --labels data/backtest/itp_<T>_labels.json --result runs/r.json
    python -m hyparena.backtest compare --labels ... --a runs/exp/L0_*.json --b runs/exp/L4_*.json --split test

Splits: every item is assigned to `dev` (for tuning prompts and weights) or `test` (for the one final
comparison), stratified by label and deterministic (hash of the compound name). Items that a judge model
already knows (hyparena.leakage) can be excluded with --exclude-known.

ITP pool (historical, for T before 2023): ITP tests from DrugAge (HAGR, CC BY 3.0; rows flagged ITP), one
per compound and regimen (dosage, age at initiation): a repeat at another dose or start age is its own
hypothesis. A test enters the pool if its first ITP publication is after T. Labels supports / no_effect /
harmful, with the result per sex and the effect size apart. For T after 2022 the outcomes come from the batch
papers themselves (hyparena/outcomes.py; DrugAge has few post-2022 entries). The hypothesis text states the
intervention and the claimed effect, not the outcome. Labels go to a separate file that the pipeline never
reads; metrics are computed outside the graph (hidden evaluation).

Leakage (Working_Notes A2, 2026-10-20): models are chosen by training cutoff <= T (hyparena.outcomes models);
the leakage probe (hyparena.leakage, --exclude-known) is not used for method v2. Pools whose results models
may know (`historical`) are for our system only, whose evidence is cut at T."""
from __future__ import annotations

from dataclasses import replace

import argparse
import csv
import glob
import hashlib
import io
import json
import random
import zipfile
from collections import defaultdict
from typing import Optional
from pathlib import Path

import httpx

DRUGAGE_URL = "https://genomics.senescence.info/drugs/dataset.zip"
OUT = Path(__file__).resolve().parents[1] / "data" / "backtest"


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _pubmed_date(text: str) -> str | None:
    """ISO date from a PubMed date string ("2016 Nov 14", "2016 Dec", "2016/11/15 06:00"); a missing day or
    month counts as the first."""
    parts = text.replace("/", " ").replace("-", " ").split()
    if not parts or not parts[0].isdigit() or len(parts[0]) != 4:
        return None
    month, day = 1, 1
    if len(parts) > 1:
        month = int(parts[1]) if parts[1].isdigit() else _MONTHS.get(parts[1][:3].lower(), 1)
    if len(parts) > 2 and parts[2].isdigit():
        day = int(parts[2])
    return f"{parts[0]}-{month:02d}-{day:02d}"


def _pubdates(pmids: list[str]) -> dict[str, str]:
    """PubMed id -> ISO date of first public appearance, via NCBI E-utilities (batches of 150): the earliest
    of the electronic, print and PubMed-entry dates. (The print date alone can come weeks after the paper
    was online, which let a backtest's evidence cut-off include the paper itself.)"""
    from hyparena.tools import pubmed                # shares PubMed's rate limit with the verifier's threads
    dates = {}
    for i in range(0, len(pmids), 150):
        batch = pmids[i:i + 150]
        r = pubmed._get("esummary.fcgi", {"db": "pubmed", "id": ",".join(batch), "retmode": "json"})
        res = r.json().get("result", {})
        for p in batch:
            rec = res.get(p) or {}
            found = [_pubmed_date(rec.get(k) or "") for k in ("epubdate", "pubdate", "sortpubdate")]
            found += [_pubmed_date(h.get("date", "")) for h in rec.get("history") or []
                      if h.get("pubstatus") in ("entrez", "pubmed", "aheadofprint")]
            found = [d for d in found if d]
            if found:
                dates[p] = min(found)
    return dates


def drugage_rows() -> list[dict]:
    """All rows of the current DrugAge release (downloaded each time; about 0.5 MB)."""
    raw = httpx.get(DRUGAGE_URL, timeout=120, follow_redirects=True).content
    z = zipfile.ZipFile(io.BytesIO(raw))
    return list(csv.DictReader(io.TextIOWrapper(z.open("drugage.csv"), encoding="utf-8", errors="replace")))


def _pct(v: str) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def itp_outcome(rows: list[dict]) -> dict:
    """Label of one ITP test (one compound in one regimen) from its DrugAge rows: supports (a significant
    increase of average lifespan in at least one sex), harmful (only significant decreases), else no_effect;
    with the result per sex and the effect size (the largest change of average lifespan) kept apart."""
    results = defaultdict(set)
    for r in rows:
        sig, pct = r["avg_lifespan_significance"].strip() == "S", _pct(r["avg_lifespan_change_percent"])
        results[r["gender"].strip().lower() or "pooled"].add(
            "supports" if sig and (pct or 0) > 0 else "harmful" if sig and (pct or 0) < 0 else "no_effect")
    by_sex = {sex: "supports" if "supports" in rs else "harmful" if "harmful" in rs else "no_effect"
              for sex, rs in results.items()}
    label = "supports" if "supports" in by_sex.values() else "harmful" if "harmful" in by_sex.values() else "no_effect"
    sizes = [x for x in (_pct(r["avg_lifespan_change_percent"]) for r in rows
                         if r["avg_lifespan_significance"].strip() == "S") if x is not None]
    effect = (max(sizes) if label == "supports" else min(sizes)) if sizes and label != "no_effect" else (
        0.0 if label == "no_effect" else None)
    return {"outcome": label, "by_sex": by_sex, "effect": effect}


def build_itp(as_of: str, clean_after: Optional[str] = None) -> tuple[Path, Path]:
    """Historical ITP pool from DrugAge (for T before 2023; Working_Notes A2): one test per compound and
    regimen (dosage, age at initiation), entering the pool if its first ITP publication is after T. A repeat
    at another dose or start age is its own hypothesis. Labels supports / no_effect / harmful with the result
    per sex and the effect size apart; `set` historical unless public after `clean_after`."""
    rows = drugage_rows()
    itp = [r for r in rows if r.get("ITP", "").strip().lower() == "yes"]
    by_test = defaultdict(list)
    for r in itp:
        by_test[(r["compound_name"].strip(), r["dosage"].strip(), r["age_at_initiation"].strip())].append(r)
    dates = _pubdates(sorted({r["pubmed_id"] for r in itp if r["pubmed_id"].strip()}))
    first_by_compound = defaultdict(list)
    for (compound, _, _), rs in by_test.items():
        first_by_compound[compound] += [dates[r["pubmed_id"]] for r in rs if r["pubmed_id"] in dates]
    items, labels = [], {}
    for (compound, dosage, age), rs in sorted(by_test.items()):
        pub = sorted(dates[r["pubmed_id"]] for r in rs if r["pubmed_id"] in dates)
        if not pub or pub[0] <= as_of:
            continue
        regimen = ", ".join(x for x in (f"at {dosage}" if dosage else "", f"started at {age}" if age else "") if x)
        hid = len(items) + 1
        text = (f"Dietary {compound}{f' ({regimen})' if regimen else ''} extends the median lifespan of "
                f"genetically heterogeneous UM-HET3 mice of at least one sex.")
        items.append({"id": hid, "title": text, "claim": text, "message": 0})
        res = itp_outcome(rs)
        earlier = min(first_by_compound[compound])
        labels[f"imp{hid:03d}"] = {"label": int(res["outcome"] == "supports"), **res, "compound": compound,
                                   "dose": dosage, "age_at_start": age, "first_itp_publication": pub[0],
                                   "public_date": pub[0], "program": "ITP", "species": "mouse",
                                   "set": "clean" if clean_after and pub[0] > clean_after else "historical",
                                   "repeat_of": compound if earlier < pub[0] else "",
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
    print(f"ITP tests in DrugAge (compound x regimen): {len(by_test)}; first publication after {as_of}: "
          f"{len(items)} ({pos} supports, {len(items) - pos} no effect or harmful)\n{data_path}\n{label_path}")
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


def run_v2(pool_path: str, out: str, config: str = "configs/v2.yaml", profile: str = "evidence_first",
           fake: bool = False, max_calls: int = 600, K: int = 10000, verifiers: Optional[list[str]] = None,
           limit: Optional[int] = None, split: Optional[str] = None, labels_path: Optional[str] = None) -> dict:
    """Our method v2 on a backtest pool, evidence as of the pool's date. Writes the full v2 output (`out`) and
    the ladder-format result (`out` with suffix .ladder.json) that `evaluate` and `compare` read."""
    from hyparena.card.pipeline import as_ladder_result
    from hyparena.card.pipeline import run as v2
    from hyparena.data import load_imported
    pool = json.loads(Path(pool_path).read_text())
    hyps = load_imported(pool_path)
    if split and labels_path:                               # e.g. only the dev half
        labels = json.loads(Path(labels_path).read_text())
        hyps = [h for h in hyps if labels.get(h.id, {}).get("split") == split]
    hyps = hyps[:limit] if limit else hyps
    res = v2([h.text for h in hyps], writer=pool["source"].get("family", "unknown"), config=config, fake=fake,
             as_of=pool["source"]["as_of"], max_calls=max_calls, K=K, verifiers=verifiers)
    res["meta"]["ids"] = [h.id for h in hyps]                # pool ids of the items, also for a split or a limit
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    ladder = as_ladder_result(res, [h.id for h in hyps], profile)
    Path(out).with_suffix(".ladder.json").write_text(json.dumps(ladder, indent=2))
    return ladder


def audit(v2_path: str) -> dict:
    """Date audit (Working_Notes A1): no evidence record published after the run's T reaches any component. Every
    PubMed record (and the paper behind every curated record) of every verified claim, alternative check and
    refusal is dated with PubMed's earliest public date."""
    res = json.loads(Path(v2_path).read_text())
    as_of = res["meta"].get("as_of")
    ids = {}
    for x in res["items"]:
        ver = x.get("verification") or {}
        for cv in ver.get("claims", []):
            for r in cv.get("evidence", []) + cv.get("counterevidence", []) + cv.get("refusals", []):
                pmid = (r.get("linked_pmid") or r.get("record_id", "")).replace("PMID:", "")
                if pmid.isdigit():
                    ids.setdefault(pmid, set()).add(f"{x['id']}/{cv['id']}")
        for a in ver.get("alternatives", []):
            pmid = (a.get("record_id") or "").replace("PMID:", "")
            if pmid.isdigit():
                ids.setdefault(pmid, set()).add(f"{x['id']}/{a['id']}")
    dates = _pubdates(sorted(ids)) if ids and as_of else {}
    late = {p: {"date": d, "where": sorted(ids[p])} for p, d in dates.items() if d > as_of}
    return {"as_of": as_of, "records": len(ids), "undated": sorted(set(ids) - set(dates)), "after_T": late,
            "ok": not late}


def ablate(v2_path: str, drop: list[str], profile: str = "evidence_first", K: int = 10000) -> dict:
    """The ladder-format result of a saved v2 run re-aggregated without the indicators `drop` (no model calls):
    which part of the ranking comes from which axis. Gate, known results and the other indicators as saved."""
    from hyparena.aspid import aggregate, load_profiles
    from hyparena.card import indicators as ind
    from hyparena.card.pipeline import OUTCOME_SCORE
    res = json.loads(Path(v2_path).read_text())
    ids = res["meta"].get("ids") or [f"imp{i:03d}" for i in range(1, len(res["items"]) + 1)]
    specs = [s for s in ind.INDICATORS if s.id not in drop]
    keep = {s.id for s in specs}
    values = {x["id"]: {k: v for k, v in (x.get("indicators") or {}).items() if k in keep}
              for x in res["items"] if x["outcome"] == "ranked"}
    prof = load_profiles()[profile]
    prof = replace(prof, tiers=[tier if isinstance(tier, str) else [t for t in tier if t in keep] for tier in prof.tiers])
    prof = replace(prof, tiers=[t for t in prof.tiers if t])
    expected = aggregate(values, specs, prof, K=K).expected if values else {}
    hyps = {hid: {"status": x["outcome"], "card_id": x["id"],
                  "combined": OUTCOME_SCORE.get(x["outcome"], 1.0) + (expected.get(x["id"], 0.0) if x["outcome"] == "ranked" else 0.0)}
            for hid, x in zip(ids, res["items"])}
    return {"criteria": [], "step": f"v2-without-{'-'.join(drop)}", "profile": profile, "as_of": res["meta"]["as_of"],
            "hypotheses": hyps}


PRIMARY_DROP = ["late_start"]        # reads the ITP's later choice of late-start retests (dev half, 2026-10-21)


def primary(labels_path: str, v2_path: str, split: str = "all", K: int = 10000) -> dict:
    """The backtest's primary metric, fixed before the test half was run (2026-10-21): the ranking without
    `late_start`, known results left out (they are not predictions, reported apart), one score per compound
    (the mean over its regimens; a compound is positive if any regimen is). Secondary: AUC per regimen."""
    labels = json.loads(Path(labels_path).read_text())
    hyps = ablate(v2_path, PRIMARY_DROP, K=K)["hypotheses"]
    items = {h: v for h, v in hyps.items() if h in labels and (split == "all" or labels[h].get("split") == split)}
    known = sorted(h for h, v in items.items() if v["status"] == "known_result")
    kept = {h: v for h, v in items.items() if v["status"] != "known_result"}
    score = lambda v: v["combined"] if v["combined"] is not None else -1.0
    by_compound = defaultdict(list)
    for h, v in kept.items():
        by_compound[labels[h]["compound"]].append((score(v), labels[h]["label"]))
    comp = {c: (sum(s for s, _ in xs) / len(xs), max(y for _, y in xs)) for c, xs in by_compound.items()}
    out = {"split": split, "dropped": PRIMARY_DROP,
           "known_results": [{"id": h, "compound": labels[h]["compound"], "label": labels[h]["label"]} for h in known]}
    for name, pairs in (("per_compound", list(comp.values())), ("per_regimen", [(score(v), labels[h]["label"]) for h, v in kept.items()])):
        pos, neg = [s for s, y in pairs if y == 1], [s for s, y in pairs if y == 0]
        if pos and neg:
            lo, hi = bootstrap_auc(pos, neg)
            out[name] = {"auc": auc(pos, neg), "auc_95ci": [lo, hi], "n_pos": len(pos), "n_neg": len(neg)}
    return out


def axes(labels_path: str, v2_path: str, split: str = "all") -> dict:
    """Card spec 8 validation: does each axis of the evidence profile (and each indicator) separate the later
    ITP positives from the negatives? AUC per axis over the items of the split; hypotheses filtered by the gate
    take the lowest value of every axis, items not admitted are left out."""
    from hyparena.aspid import cardinal_range
    from hyparena.card import indicators as ind
    labels = json.loads(Path(labels_path).read_text())
    items = _items(labels, split, set())
    res = json.loads(Path(v2_path).read_text())
    ids = res["meta"].get("ids") or [f"imp{i:03d}" for i in range(1, len(res["items"]) + 1)]
    by_id = dict(zip(ids, res["items"]))
    specs = {s.id: s for s in ind.INDICATORS}
    out = {"split": split, "n": 0, "outcomes": defaultdict(lambda: defaultdict(int)), "axes": {}}
    values = defaultdict(dict)
    for h, lab in items.items():
        x = by_id.get(h)
        if x is None:
            continue
        out["outcomes"][x["outcome"]][str(lab["label"])] += 1
        if x["outcome"] not in ("ranked", "known_result", "filtered"):
            continue
        out["n"] += 1
        for sid, spec in specs.items():
            if x["outcome"] == "filtered":
                v = 0.0
            else:
                raw = (x.get("indicators") or {}).get(sid)
                if raw is None:
                    continue
                v = spec.levels.index(raw) if spec.kind == "ordinal" else sum(cardinal_range(spec, raw)) / 2
            values[sid][h] = v
        values["gate_pass"][h] = 0.0 if x["outcome"] == "filtered" else 1.0
    for sid, vals in values.items():
        pos = [v for h, v in vals.items() if items[h]["label"] == 1]
        neg = [v for h, v in vals.items() if items[h]["label"] == 0]
        if pos and neg:
            lo, hi = bootstrap_auc(pos, neg)
            out["axes"][sid] = {"auc": auc(pos, neg), "auc_95ci": [lo, hi], "n_pos": len(pos), "n_neg": len(neg),
                                "distinct_values": len(set(vals.values()))}
    out["outcomes"] = {k: dict(v) for k, v in out["outcomes"].items()}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-itp")
    b.add_argument("--as-of", required=True)
    b.add_argument("--clean-after", default=None, help="latest cutoff of the models compared")
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
    v = sub.add_parser("v2", help="our method v2 on a backtest pool")
    v.add_argument("--pool", required=True)
    v.add_argument("--out", required=True)
    v.add_argument("--config", default="configs/v2.yaml")
    v.add_argument("--profile", default="evidence_first")
    v.add_argument("--max-calls", type=int, default=600)
    v.add_argument("--fake", action="store_true")
    v.add_argument("--verifiers", default=None, help="comma-separated families that verify (default: all)")
    v.add_argument("--limit", type=int, default=None, help="only the first N items")
    v.add_argument("--split", choices=["dev", "test"], default=None, help="only this split (needs --labels)")
    v.add_argument("--labels", default=None)
    pm = sub.add_parser("primary", help="the primary metric (without late_start, known results apart, per compound)")
    pm.add_argument("--labels", required=True)
    pm.add_argument("--v2", required=True)
    pm.add_argument("--split", choices=["dev", "test", "all"], default="all")
    ab = sub.add_parser("ablate", help="re-aggregate a saved v2 run without some indicators (no model calls)")
    ab.add_argument("--v2", required=True)
    ab.add_argument("--drop", required=True, help="comma-separated indicator ids")
    ab.add_argument("--profile", default="evidence_first")
    ab.add_argument("--out", required=True)
    d = sub.add_parser("audit", help="no record after T reached the run (date audit)")
    d.add_argument("--v2", required=True)
    a = sub.add_parser("axes", help="AUC of each evidence-profile axis against the labels (card spec 8)")
    a.add_argument("--labels", required=True)
    a.add_argument("--v2", required=True, help="full v2 output written by the v2 command")
    a.add_argument("--split", choices=["dev", "test", "all"], default="all")
    args = ap.parse_args()
    fams = args.known_families.split(",") if getattr(args, "known_families", None) else None
    if args.cmd == "v2":
        print(json.dumps(run_v2(args.pool, args.out, args.config, args.profile, args.fake, args.max_calls,
                                verifiers=args.verifiers.split(",") if args.verifiers else None,
                                limit=args.limit, split=args.split, labels_path=args.labels), indent=1)[:2000])
        return
    if args.cmd == "primary":
        print(json.dumps(primary(args.labels, args.v2, args.split), indent=2))
        return
    if args.cmd == "ablate":
        out = ablate(args.v2, args.drop.split(","), args.profile)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(out, indent=2))
        print(args.out)
        return
    if args.cmd == "audit":
        print(json.dumps(audit(args.v2), indent=1))
        return
    if args.cmd == "axes":
        print(json.dumps(axes(args.labels, args.v2, args.split), indent=2))
        return
    if args.cmd == "build-itp":
        build_itp(args.as_of, args.clean_after)
    elif args.cmd == "evaluate":
        print(json.dumps(evaluate(args.labels, args.result, args.split, args.unrated, args.exclude_known, fams), indent=2))
    else:
        expand = lambda ps: sorted(f for p in ps for f in (glob.glob(p) or [p]))
        print(json.dumps(compare(args.labels, expand(args.a), expand(args.b), args.split, args.unrated, args.key,
                                 args.exclude_known, fams), indent=2))


if __name__ == "__main__":
    main()

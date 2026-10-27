"""L1.10: agreement of verifier families on the status of the main claim (Cohen's kappa), same cards, only the verifier changes.

    python -m scripts.verifier_agreement select                          # no calls: 30 ITP regimens, data/validation/l1_10_pool.json
    ALLOW_PAID=1 python -m scripts.verifier_agreement run --out runs/stage5/l1_10   # one pipeline run per family (deepseek, google, zhipu)
    python -m scripts.verifier_agreement report --dir runs/stage5/l1_10

Cards come from the earlier ITP runs (no normalizer); evidence is read as of today (no date guard: the check is about the verifiers agreeing
with one another, not about the date), alternatives and duplicates off. Statuses: supported, refuted, contested, unverified.
The criterion is in specs/validation-criteria.yaml (L1.10).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

POOL = Path("data/validation/l1_10_pool.json")
FAMILIES = ["deepseek", "google", "zhipu"]
N = 30
MIN_UNITS = 25
KAPPA_MIN = 0.6
MIN_NON_UNVERIFIED = 5


def _norm(v) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v or "").lower())


def select() -> list[dict]:
    """Up to 30 ranked ITP regimens of distinct compounds, at most 15 with a later positive label and 15 with a negative one, by a hash of the text (27 exist: 12 and 15)."""
    labels = json.loads(Path("data/backtest/itp_2010-12-31_labels.json").read_text())
    rows = []
    for half in ("dev", "test"):
        res = json.loads(Path(f"runs/stage4/itp2010_{half}.json").read_text())
        ids = res["meta"].get("ids") or []
        for pid, x in zip(ids, res["items"]):
            if x["outcome"] == "ranked" and x.get("card") and pid in labels:
                rows.append({"id": pid, "compound": labels[pid]["compound"], "label": labels[pid]["label"], "text": x["text"], "card": x["card"]})
    rows.sort(key=lambda r: hashlib.sha1(r["text"].encode()).hexdigest())
    seen, out, per = set(), [], Counter()
    for r in rows:
        if _norm(r["compound"]) in seen or per[r["label"]] >= N // 2:
            continue
        seen.add(_norm(r["compound"]))
        per[r["label"]] += 1
        out.append(r)
    return out


def kappa(a: list, b: list) -> float | None:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else (po - pe) / (1 - pe)


def kappa_ci(a: list, b: list, draws: int = 2000, seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        idx = [rng.randrange(len(a)) for _ in a]
        k = kappa([a[i] for i in idx], [b[i] for i in idx])
        if k is not None:
            vals.append(k)
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 3), round(vals[int(0.975 * len(vals)) - 1], 3)] if vals else [None, None]


def statuses(res: dict) -> list[str]:
    out = []
    for x in res["items"]:
        cl = (x.get("verification") or {}).get("claims") or []
        out.append(cl[0]["status"] if cl else x["outcome"])
    return out


def verdict(st: dict[str, list[str]]) -> dict:
    fams = list(st)
    pairs, out = {}, {"counts": {f: dict(Counter(st[f])) for f in fams}}
    for i, a in enumerate(fams):
        for b in fams[i + 1:]:
            k = kappa(st[a], st[b])
            pairs[f"{a}-{b}"] = {"kappa": None if k is None else round(k, 3), "ci": kappa_ci(st[a], st[b]),
                                 "agree": round(sum(x == y for x, y in zip(st[a], st[b])) / len(st[a]), 3)}
    out["pairs"] = pairs
    ref = st[fams[0]]
    informative = len(ref) >= MIN_UNITS and sum(s != "unverified" for s in ref) >= MIN_NON_UNVERIFIED
    ok = all(v["kappa"] is not None and v["kappa"] >= KAPPA_MIN for v in pairs.values())
    out["status"] = "uninformative" if not informative else "pass" if ok else "fail"
    return out


def cmd_run(out: str, max_calls: int) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from hyparena.card import pipeline
    d = json.loads(POOL.read_text())
    Path(out).mkdir(parents=True, exist_ok=True)

    def one(fam):
        res = pipeline.run([r["text"] for r in d["items"]], config=f"configs/v2-agree-{fam}.yaml", as_of=None, max_calls=max_calls,
                           verifiers=[fam], cards=[r["card"] for r in d["items"]], check_alternatives=False, dedup=False)
        Path(out, f"{fam}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        return fam, res["meta"]["calls"]

    with ThreadPoolExecutor(3) as pool:
        for fam, calls in pool.map(one, FAMILIES):
            print(fam, "calls", calls, flush=True)


def cmd_report(dirname: str) -> dict:
    st = {f: statuses(json.loads(Path(dirname, f"{f}.json").read_text())) for f in FAMILIES}
    out = verdict(st)
    print(json.dumps(out, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("select")
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--max-calls", type=int, default=600)
    q = sub.add_parser("report")
    q.add_argument("--dir", required=True)
    a = ap.parse_args()
    if a.cmd == "select":
        items = select()
        POOL.parent.mkdir(parents=True, exist_ok=True)
        POOL.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1))
        print(len(items), "regimens;", Counter(r["label"] for r in items))
    elif a.cmd == "run":
        cmd_run(a.out, a.max_calls)
    else:
        cmd_report(a.dir)


if __name__ == "__main__":
    main()

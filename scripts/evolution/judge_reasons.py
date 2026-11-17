"""The free reasons of pairwise judgements put into the four considerations of the judge question (specs/evolution/
generation-comparison-2026-11-16-pilot.yaml, judge_reasons_2026_11_17). Paid (cents). Only counts are printed.

    ALLOW_PAID=1 python -m scripts.evolution.judge_reasons --dir …/generation-2026-11-16
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

LABELS = ("mechanism", "evidence", "benefit", "experiment", "other")
BATCH = 20


def side(key: str, v: dict) -> str:
    """'x' when the judgement went to the first hypothesis of the comparison (BS in BS>A), 'y' to the second, else 'tie'."""
    order = key.rsplit("|", 1)[1]
    if v["overall"] == "tie":
        return "tie"
    return "x" if (v["overall"] == "1") == (order == "ab") else "y"


def main() -> None:
    from hyparena.card.llm import ask
    from hyparena.pipeline import _client
    from hyparena.reports.usage import summarize
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--family", default="deepseek")
    a = ap.parse_args()
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid call: set ALLOW_PAID=1")
    d = Path(a.dir)
    judg = {k: v for k, v in json.loads((d / "judgements.json").read_text()).items() if v and v.get("reason")}
    out_f = d / "judge_reasons.json"
    labels = json.loads(out_f.read_text()) if out_f.exists() else {}
    todo = [k for k in judg if k not in labels]
    client, _ = _client("configs/judges-generation.yaml", False, 50)
    log: list = []
    for i in range(0, len(todo), BATCH):
        part = todo[i:i + BATCH]
        items = [{"n": j + 1, "text": judg[k]["reason"]} for j, k in enumerate(part)]
        ok = lambda v: [] if isinstance(v.get("labels"), dict) and all(v["labels"].get(str(j + 1)) in LABELS for j in range(len(part))) \
            else ["a label from the list for every item"]
        v, _ = ask(client, role="classify_reason", family=a.family, template="classify_reason", version="v1",
                   variables={"reasons": items}, validate=ok, rounds=2, log=log)
        for j, k in enumerate(part):
            labels[k] = (v or {}).get("labels", {}).get(str(j + 1))
        out_f.write_text(json.dumps(labels, indent=1) + "\n")
    names = {"x": "BS", "y": "A", "tie": "tie"}
    by_side, by_family = defaultdict(Counter), defaultdict(lambda: defaultdict(Counter))
    for k, lab in labels.items():
        s = names[side(k, judg[k])]
        by_side[s][lab] += 1
        by_family[k.split("|")[4]][s][lab] += 1
    res = {"judgements": len(labels), "unlabelled": sum(v is None for v in labels.values()),
           "by_winner": {s: dict(c) for s, c in by_side.items()},
           "by_family": {f: {s: dict(c) for s, c in x.items()} for f, x in by_family.items()}, "usage": summarize(log)["total"]}
    (d / "judge_reasons_summary.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "by_family"}, indent=1))


if __name__ == "__main__":
    main()

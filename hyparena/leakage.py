"""Leakage probe: which backtest items does each judge model already know the outcome of?

    python -m hyparena.leakage --pool data/backtest/itp_<T>.json --labels data/backtest/itp_<T>_labels.json \
        --config configs/paid-test.yaml --out data/backtest/itp_<T>_known.json   [--fake] [--families a,b]

Each enabled model is asked, item by item, whether the claim was tested and what the result was. An item is
"known" to a family if the model names the correct outcome (supported for label 1, refuted for label 0)
with confidence >= --min-confidence. Known items can then be excluded from evaluation
(`backtest evaluate/compare --exclude-known`). Costs one call per item and model: run it once per pool."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from hyparena.llm.fake import FakeLLMClient
from hyparena.llm.judges import JudgeSpec
from hyparena.llm.prompts import render
from hyparena.llm.providers import DEFAULT_CONFIG, GuardedClient, build_client, load_config
from hyparena.llm.structured import parse_json

OUTCOME = {1: "supported", 0: "refuted"}


def probe(pool_path: str, labels_path: str, client, judges: list[JudgeSpec], min_confidence: float = 0.6) -> dict:
    pool = json.loads(Path(pool_path).read_text())["hypotheses"]
    labels = json.loads(Path(labels_path).read_text())
    known, answers = {}, {}
    for j in judges:
        known[j.family], answers[j.family] = [], {}
        for item in pool:
            hid = f"imp{item['id']:03d}"
            if hid not in labels:
                continue
            reply = client.call(role="leakage", family=j.family, prompt=render("leakage", "v1", claim=item["claim"]))
            v = parse_json(reply.text) or {}
            result, conf = str(v.get("result", "unknown")), float(v.get("confidence") or 0)
            answers[j.family][hid] = {"result": result, "confidence": conf, "error": reply.error}
            if result == OUTCOME[labels[hid]["label"]] and conf >= min_confidence:
                known[j.family].append(hid)
    summary = {fam: {"known": len(ids), "asked": len(answers[fam]),
                     "answers": dict(Counter(a["result"] for a in answers[fam].values()))} for fam, ids in known.items()}
    return {"pool": pool_path, "min_confidence": min_confidence, "known": known, "summary": summary, "answers": answers}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--families", default=None)
    ap.add_argument("--min-confidence", type=float, default=0.6)
    ap.add_argument("--max-calls", type=int, default=1000)
    ap.add_argument("--fake", action="store_true", help="fake LLM, no model calls")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.fake:
        specs = [s for s in load_config(args.config).models if s.enabled]
        judges = [JudgeSpec(s.family, f"fake-{s.model}") for s in specs]
        client = GuardedClient(FakeLLMClient(0), rpm=0, max_calls=args.max_calls)
    else:
        client, judges, _ = build_client(args.config, max_calls=args.max_calls)
    if args.families:
        judges = [j for j in judges if j.family in args.families.split(",")]
    result = probe(args.pool, args.labels, client, judges, args.min_confidence)
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(json.dumps(result["summary"], indent=2), f"\ncalls: {client.calls}\nwritten to {args.out}")


if __name__ == "__main__":
    main()

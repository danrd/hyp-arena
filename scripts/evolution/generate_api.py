"""Generation by a model through the provider's Responses endpoint with web search (specs/evolution/
generation-comparison-2026-11-16-pilot.yaml, round_5_api_2026_11_17). Paid. The task files are the chat tasks of a round
(task_<kind>.json in GEN_DIR); the answer is written to answer_<kind>.json and the raw reply to raw_<kind>.json. Nothing of
the hypotheses is printed: only status, tokens, searches and cost.

    ALLOW_PAID=1 GEN_DIR=…/generation-2026-11-17-sol python -m scripts.evolution.generate_api --kinds a bs [--cap 2]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import httpx

URL = "https://api.cometapi.com/v1/responses"
PRICE = {"gpt-6.1-sol": {"in": 2.0, "out": 10.0, "cache_write": 2.5, "search_per_call": 0.01}}   # configs/prices.yaml
API_LINE = ("You may use web search to find and check papers. Cite only papers published on or before T, with their real "
            "PMIDs.")


def prompt(task: dict) -> str:
    body = {k: v for k, v in task.items() if k != "cover"}
    body["instructions"] = list(body.get("instructions") or []) + [API_LINE]
    return task["cover"] + "\n\n" + json.dumps(body, indent=1, ensure_ascii=False)


def cost(model: str, usage: dict, searches: int) -> float:
    p = PRICE[model]
    cw = (usage.get("input_tokens_details") or {}).get("cache_write_tokens", 0)
    return round((usage.get("input_tokens", 0) - cw) / 1e6 * p["in"] + cw / 1e6 * p["cache_write"]
                 + usage.get("output_tokens", 0) / 1e6 * p["out"] + searches * p["search_per_call"], 4)


def call(model: str, text: str) -> tuple[dict, dict]:
    key = os.environ.get("COMET_API_KEY") or os.environ.get("COMETAPI_KEY")
    body = {"model": model, "input": text, "tools": [{"type": "web_search"}], "max_tool_calls": 25,
            "max_output_tokens": 32000, "reasoning": {"effort": "medium"}}
    t0 = time.time()
    r = httpx.post(URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=900)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:2000]}
    items = data.get("output") or []
    meta = {"http_status": r.status_code, "seconds": round(time.time() - t0, 1), "status": data.get("status"),
            "searches": sum(i.get("type") == "web_search_call" for i in items), "usage": data.get("usage") or {},
            "error": data.get("error"), "incomplete": data.get("incomplete_details")}
    return data, meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kinds", nargs="+", default=["a", "bs"])
    ap.add_argument("--model", default="gpt-6.1-sol")
    ap.add_argument("--cap", type=float, default=2.0)
    a = ap.parse_args()
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid call: set ALLOW_PAID=1")
    d = Path(os.environ["GEN_DIR"])
    spent, log = 0.0, []
    for kind in a.kinds:
        if spent > a.cap / 2:
            log.append({"kind": kind, "skipped": f"spent {spent} USD, over half the cap"})
            break
        task = json.loads((d / f"task_{kind}.json").read_text())
        data, meta = call(a.model, prompt(task))
        (d / f"raw_{kind}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        meta["usd"] = cost(a.model, meta["usage"], meta["searches"])
        spent += meta["usd"]
        text = "".join(c.get("text", "") for i in data.get("output") or [] if i.get("type") == "message"
                       for c in i.get("content") or [])
        m = re.search(r"\{.*\}", text, re.S)
        try:
            ans = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            ans = None
        meta["answer_parsed"] = bool(ans and isinstance(ans.get("hypotheses"), list))
        if meta["answer_parsed"]:
            (d / f"answer_{kind}.json").write_text(json.dumps(ans, indent=1, ensure_ascii=False) + "\n")
            meta["hypotheses"] = len(ans["hypotheses"])
            meta["chars"] = [len((h.get("claim") or "") + (h.get("rationale") or "") + (h.get("experiment") or ""))
                             for h in ans["hypotheses"]]
        log.append({"kind": kind, **{k: v for k, v in meta.items() if k != "usage"},
                    "tokens_in": meta["usage"].get("input_tokens"), "tokens_out": meta["usage"].get("output_tokens")})
    (d / "generation_log.json").write_text(json.dumps({"model": a.model, "spent_usd": round(spent, 4), "calls": log},
                                                      indent=1) + "\n")
    print(json.dumps({"model": a.model, "spent_usd": round(spent, 4), "calls": log}, indent=1))


if __name__ == "__main__":
    main()

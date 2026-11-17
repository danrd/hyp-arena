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
PRICE = {"gpt-6.1-sol": {"in": 2.0, "out": 10.0, "cache_write": 2.5, "search_per_call": 0.01},
         "qwen4-max": {"in": 1.5, "out": 4.5, "cache_write": 1.875, "search_per_call": 0.0}}   # no search price in the catalog   # configs/prices.yaml
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
    # streamed (2026-11-17): a long call with searches kept the connection silent for minutes and the server closed it
    # without a response; with stream the events keep it open and the final event carries the whole response
    body["stream"] = True
    data, status, events = {}, None, 0
    try:
        with httpx.stream("POST", URL, json=body, headers={"Authorization": f"Bearer {key}"},
                          timeout=httpx.Timeout(60, read=600)) as r:
            status = r.status_code
            if status != 200:
                r.read()
                data = {"error": r.text[:2000]}
            else:
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    events += 1
                    ev = json.loads(payload)
                    if ev.get("type") in ("response.completed", "response.incomplete", "response.failed"):
                        data = ev.get("response") or {}
    except httpx.HTTPError as e:
        data = {"error": f"{type(e).__name__}: {e}"}
    items = data.get("output") or []
    meta = {"http_status": status, "events": events, "seconds": round(time.time() - t0, 1), "status": data.get("status"),
            "searches": sum(i.get("type") == "web_search_call" for i in items), "usage": data.get("usage") or {},
            "error": data.get("error"), "incomplete": data.get("incomplete_details")}
    return data, meta


def billing():
    """The provider's running total of the account's usage (its own unit), read before and after: a cost check that does
    not depend on the reply's usage block (a call cut off without a response may still be billed)."""
    key = os.environ.get("COMET_API_KEY") or os.environ.get("COMETAPI_KEY")
    try:
        return httpx.get("https://api.cometapi.com/v1/dashboard/billing/usage", headers={"Authorization": f"Bearer {key}"},
                         timeout=20).json().get("total_usage")
    except (httpx.HTTPError, ValueError):
        return None


def call_background(model: str, text: str, poll: int = 15, limit: int = 3600) -> tuple[dict, dict]:
    """Background mode: the request is accepted at once and its result fetched by polling, so no stream limit applies."""
    key = os.environ.get("COMET_API_KEY") or os.environ.get("COMETAPI_KEY")
    h = {"Authorization": f"Bearer {key}"}
    body = {"model": model, "input": text, "tools": [{"type": "web_search"}], "max_tool_calls": 25,
            "max_output_tokens": 32000, "reasoning": {"effort": "medium"}, "background": True}
    t0 = time.time()
    r = httpx.post(URL, json=body, headers=h, timeout=120)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"error": r.text[:2000]}
    rid, polls = data.get("id"), 0
    while rid and data.get("status") in ("queued", "in_progress") and time.time() - t0 < limit:
        time.sleep(poll)
        polls += 1
        try:
            g = httpx.get(f"{URL}/{rid}", headers=h, timeout=60)
            if g.headers.get("content-type", "").startswith("application/json"):
                data = g.json()
        except httpx.HTTPError:
            continue
    items = data.get("output") or []
    meta = {"http_status": r.status_code, "mode": "background", "id": rid, "polls": polls,
            "seconds": round(time.time() - t0, 1), "status": data.get("status"),
            "searches": sum(i.get("type") == "web_search_call" for i in items), "usage": data.get("usage") or {},
            "error": data.get("error"), "incomplete": data.get("incomplete_details")}
    return data, meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kinds", nargs="+", default=["a", "bs"])
    ap.add_argument("--model", default="gpt-6.1-sol")
    ap.add_argument("--cap", type=float, default=2.0)
    ap.add_argument("--background", action="store_true", help="background mode with polling instead of a stream")
    ap.add_argument("--pause", type=int, default=0, help="seconds between the calls (the upstream's token rate limit)")
    a = ap.parse_args()
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid call: set ALLOW_PAID=1")
    d = Path(os.environ["GEN_DIR"])
    spent, log = 0.0, []
    billing_before = billing()
    for kind in a.kinds:
        if spent > a.cap / 2:
            log.append({"kind": kind, "skipped": f"spent {spent} USD, over half the cap"})
            break
        if log and a.pause:
            time.sleep(a.pause)
        task = json.loads((d / f"task_{kind}.json").read_text())
        data, meta = (call_background if a.background else call)(a.model, prompt(task))
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
    res = {"model": a.model, "spent_usd": round(spent, 4), "billing_total_before": billing_before,
           "billing_total_after": billing(), "calls": log}
    (d / "generation_log.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

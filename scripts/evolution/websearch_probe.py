"""Paid probe (about 0.05 USD at most): does the provider's Responses endpoint give an OpenAI model its web search tool, what
does a call cost, and are the tokens reported? One question with a known answer (the PMID of a well-known trial), checked
by code against PubMed. Needs COMET_API_KEY and ALLOW_PAID=1.

    ALLOW_PAID=1 python -m scripts.evolution.websearch_probe [--model gpt-6.1-sol]
    # -> longevity-kg reviews/generation-2026-11-17/websearch_probe.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import httpx

KG = Path(__file__).resolve().parents[2].parent / "longevity-kg"
OUT = KG / "reviews" / "generation-2026-11-17" / "websearch_probe.json"
URL = "https://api.cometapi.com/v1/responses"
PRICE = {"gpt-6.1-sol": {"in": 2.0, "out": 10.0, "search_per_call": 0.01}}      # configs/prices.yaml; search 10 USD / 1000
QUESTION = ("Use web search. Find the randomized controlled trial of levothyroxine in older adults with subclinical "
            "hypothyroidism published in the New England Journal of Medicine in 2017 (the TRUST trial). Reply with one JSON "
            'object only: {"pmid": "", "title": "", "year": 0, "source_url": ""}.')
EXPECTED_PMID = "28402245"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="gpt-6.1-sol")
    a = ap.parse_args()
    if os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid call: set ALLOW_PAID=1")
    key = os.environ.get("COMET_API_KEY") or os.environ.get("COMETAPI_KEY")
    body = {"model": a.model, "input": QUESTION, "tools": [{"type": "web_search"}], "max_output_tokens": 2000,
            "reasoning": {"effort": "low"}}
    t0 = time.time()
    r = httpx.post(URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=180)
    out = {"model": a.model, "http_status": r.status_code, "seconds": round(time.time() - t0, 1)}
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text[:2000]}
    items = data.get("output") or []
    out["output_types"] = [i.get("type") for i in items]
    out["searches"] = sum(i.get("type") == "web_search_call" for i in items)
    text = "".join(c.get("text", "") for i in items if i.get("type") == "message" for c in i.get("content") or [])
    out["text"] = text[:1500]
    usage = data.get("usage") or {}
    out["usage"] = usage
    out["error"] = data.get("error") or (None if r.status_code == 200 else str(data)[:800])
    m = re.search(r"\{.*\}", text, re.S)
    ans = json.loads(m.group(0)) if m else {}
    out["pmid_given"] = str(ans.get("pmid", ""))
    out["pmid_correct"] = out["pmid_given"] == EXPECTED_PMID
    p = PRICE.get(a.model)
    if p and usage:
        out["usd"] = round(usage.get("input_tokens", 0) / 1e6 * p["in"] + usage.get("output_tokens", 0) / 1e6 * p["out"]
                           + out["searches"] * p["search_per_call"], 4)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "text"}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

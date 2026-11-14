"""Resources of a run: calls, tokens, seconds and USD per stage of the method, computed by code from the call log.

    python -m hyparena.usage RUN.json [RUN2.json ...]        # a pipeline run, a benchmark output or any JSON with call logs
    python -m hyparena.usage --pack TASK.json ANSWER.json    # an outside reader's pack (chat, no API): an estimate by text size

The cost is never taken from a model's own report: within the code every call is logged with its model and the tokens the
API returned, and the price comes from configs/prices.yaml (with the peak hours of a family). Work done outside the code,
in a chat (an outside reader working from the manual), has no API count: its tokens are estimated from the text it was
given and the text it returned (characters / 3.6 for English, / 2.6 for Cyrillic; about +-20%), marked "estimate".
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

import yaml

PRICES = Path(__file__).resolve().parents[1] / "configs" / "prices.yaml"

# stage of the method (docs/system/flow_base.png) by the template, else by the role of the call
STAGE_BY_TEMPLATE = {"normalize_card": "card", "normalize": "card", "card_baseline": "card (baseline)",
                     "search_queries": "search", "verify_claim": "reading", "relevance_check": "reading",
                     "reading_baseline": "reading (baseline)", "estimand": "endpoint", "judge_alternatives": "alternatives",
                     "propose_alternatives": "alternatives", "check_alternatives": "alternatives",
                     "evolve_v3": "versions", "evolve_free": "versions", "generate": "generation"}
STAGES_ORDER = ["card", "search", "reading", "alternatives", "endpoint", "versions", "generation"]


@lru_cache(maxsize=1)
def prices() -> dict:
    return yaml.safe_load(PRICES.read_text())


def stage_of(call: dict) -> str:
    t = str(call.get("template") or "").split("/")[0]
    return STAGE_BY_TEMPLATE.get(t) or STAGE_BY_TEMPLATE.get(str(call.get("role") or "")) or (call.get("role") or "other")


def _peak(family: str, at: Optional[str]) -> float:
    rule = (prices().get("peak") or {}).get(family or "")
    if not rule or not at:
        return 1.0
    try:
        t = datetime.fromisoformat(at).astimezone(timezone.utc)
    except ValueError:
        return 1.0
    if t.weekday() in rule["weekdays"] and any(a <= t.hour < b for a, b in rule["hours"]):
        return float(rule["multiplier"])
    return 1.0


def cost(model: str, tokens_in: int, tokens_out: int, family: str = "", at: Optional[str] = None) -> Optional[float]:
    """USD of one call; None when the model has no price in configs/prices.yaml."""
    model = model or (prices().get("family_default") or {}).get(family or "", "")
    p = (prices().get("models") or {}).get(model)
    if not p:
        return None
    return (tokens_in * p["in"] + tokens_out * p["out"]) / 1e6 * _peak(family, at)


def estimate_tokens(text: str) -> int:
    """Tokens of a text that went through no API (an outside reader in a chat): characters / 2.6 for Cyrillic, / 3.6 else."""
    cyr = len(re.findall(r"[а-яА-ЯёЁ]", text or ""))
    return round(cyr / 2.6 + (len(text or "") - cyr) / 3.6)


def summarize(calls: Iterable[dict]) -> dict:
    """{stages: {stage: {calls, tokens_in, tokens_out, seconds, usd}}, total: {...}, models: {...}, unpriced: [...]}."""
    st = defaultdict(lambda: {"calls": 0, "tokens_in": 0, "tokens_out": 0, "seconds": 0.0, "usd": 0.0})
    models, unpriced = defaultdict(int), set()
    for c in calls:
        if c.get("kind", "llm") != "llm" and "tokens_in" not in c:
            continue
        s = st[stage_of(c)]
        ti, to = int(c.get("tokens_in") or 0), int(c.get("tokens_out") or 0)
        s["calls"] += 1; s["tokens_in"] += ti; s["tokens_out"] += to; s["seconds"] += float(c.get("seconds") or 0)
        usd = cost(c.get("model") or "", ti, to, c.get("family") or "", c.get("at"))
        if usd is None:
            unpriced.add(c.get("model") or f"family {c.get('family') or 'unknown'}")
        else:
            s["usd"] += usd
        models[c.get("model") or "unknown"] += 1
    order = sorted(st, key=lambda k: STAGES_ORDER.index(k) if k in STAGES_ORDER else 99)
    stages = {k: {**st[k], "seconds": round(st[k]["seconds"], 1), "usd": round(st[k]["usd"], 4)} for k in order}
    total = {f: (round(sum(v[f] for v in stages.values()), 4) if f in ("usd", "seconds") else sum(v[f] for v in stages.values()))
             for f in ("calls", "tokens_in", "tokens_out", "seconds", "usd")}
    return {"stages": stages, "total": total, "models": dict(models), "unpriced": sorted(unpriced)}


def _calls_in(obj) -> list[dict]:
    """Every call-log entry anywhere in a JSON (pipeline runs keep `calls` per unit, benchmark outputs per text)."""
    out = []
    if isinstance(obj, dict):
        if "tokens_in" in obj and ("template" in obj or "role" in obj):
            return [obj]
        for v in obj.values():
            out += _calls_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _calls_in(v)
    return out


def summarize_file(path: str) -> dict:
    data = json.loads(Path(path).read_text())
    res = summarize(_calls_in(data))
    units = data if isinstance(data, dict) else {}
    per = [summarize(_calls_in(v))["total"]["usd"] for v in units.values() if isinstance(v, (dict, list))]
    per = [x for x in per if x]
    if per:
        res["per_unit_usd"] = {"units": len(per), "mean": round(sum(per) / len(per), 4), "max": round(max(per), 4)}
    return res


def summarize_pack(task: str, answer: str) -> dict:
    """An outside reader's pack done in a chat: tokens estimated from the texts (no API count, no price)."""
    tin, tout = estimate_tokens(Path(task).read_text()), estimate_tokens(Path(answer).read_text())
    return {"tokens_in_estimate": tin, "tokens_out_estimate": tout, "basis": "estimate from text size (+-20%), not an API count",
            "usd": None}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--pack", nargs=2, metavar=("TASK", "ANSWER"))
    a = ap.parse_args()
    out = {"pack": summarize_pack(*a.pack)} if a.pack else {f: summarize_file(f) for f in a.files}
    print(json.dumps(out, indent=1, ensure_ascii=False))

"""Informativeness (card spec 8c): how many of the open alternative explanations the decisive experiment of the
hypothesis, as written, discriminates (0 to 4). One call per hypothesis; code keeps an alternative only when the
phrase that states the control is copied verbatim from the hypothesis text, so the count cannot rest on what the
model imagines the experiment could include.

    python -m hyparena.card.informativeness --v2 runs/x.json --out runs/x.info.json --config configs/v2-flash.yaml"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional

from hyparena.card.llm import ask
from hyparena.card.models import HypothesisCard, Verification

TEMPLATE = ("informativeness", "v1")
CAP = 4                                                  # the scale of the indicator is 0..4
COUNTED = ("checklist", "declared")                      # competitors of the pool are other hypotheses, not explanations


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("‐", "-").replace("–", "-")).strip().lower()


def candidates(ver: Verification) -> list:
    """The alternatives the experiment could discriminate: not excluded by the literature already."""
    return [a for a in ver.alternatives if a.source in COUNTED and a.status != "excluded_by_evidence"]


def _validate(value: dict, ids: set[str], text: str) -> list[str]:
    items = value.get("discriminated")
    if not isinstance(items, list):
        return ['the reply must be an object with a "discriminated" list']
    problems = []
    for x in items:
        if not isinstance(x, dict) or x.get("id") not in ids:
            problems.append(f"unknown alternative id: {x!r}")
        elif _norm(x.get("how", "")) not in _norm(text) or not _norm(x.get("how", "")):
            problems.append(f"{x.get('id')}: the phrase is not copied verbatim from the hypothesis text")
    return problems


def discriminated(client, family: str, text: str, card: HypothesisCard, ver: Verification,
                  avoid: frozenset = frozenset(), log: Optional[list] = None) -> Optional[dict]:
    """{"n": count (capped at 4), "of": candidates, "items": [{id, explanation, how}]}, or None when the reply failed."""
    cands = candidates(ver)
    if not cands:
        return {"n": 0, "of": 0, "items": []}
    ids = {a.id for a in cands}
    value, _ = ask(client, role="informativeness", family=family, template=TEMPLATE[0], version=TEMPLATE[1],
                   variables={"text": text, "alternatives": [{"id": a.id, "explanation": a.explanation, "design": a.discriminating_design}
                                                              for a in cands]},
                   validate=lambda v: _validate(v, ids, text), rounds=2, avoid=avoid, log=log)
    if not isinstance(value, dict) or not isinstance(value.get("discriminated"), list):
        return None
    by_id = {a.id: a for a in cands}
    kept = {}
    for x in value["discriminated"]:
        if isinstance(x, dict) and x.get("id") in by_id and x.get("id") not in kept and _norm(x.get("how", "")) \
                and _norm(x["how"]) in _norm(text):
            kept[x["id"]] = {"id": x["id"], "explanation": by_id[x["id"]].explanation, "how": x["how"]}
    return {"n": min(CAP, len(kept)), "of": len(cands), "items": list(kept.values())}


def add_to_result(res: dict, client, family: str, log: Optional[list] = None, only: Optional[set] = None) -> int:
    """Informativeness for the gate-passing hypotheses of a saved v2 result (written to `extra`); returns the calls made."""
    before = getattr(client, "calls", 0)
    for x in res["items"]:
        if not x.get("verification") or (only is not None and x["id"] not in only):
            continue
        ver = Verification.model_validate(x["verification"])
        if ver.evidence_profile.gate != "pass":
            continue
        card = HypothesisCard.model_validate(x["card"])
        info = discriminated(client, family, x["text"], card, ver, log=log)
        if info is not None:
            x.setdefault("extra", {}).update({"informativeness": info["n"], "informativeness_detail": info})
    return getattr(client, "calls", 0) - before


def main() -> None:
    from hyparena.card.pipeline import _client, reapply_rules
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v2", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default="configs/v2-flash.yaml")
    ap.add_argument("--family", default="deepseek")
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args()
    res = json.loads(Path(a.v2).read_text())
    client, _ = _client(a.config, a.fake, a.max_calls)
    n = add_to_result(res, client, a.family)
    res = reapply_rules(res, new_rules=False)             # the ranking again with the new indicator, nothing else changed
    res["meta"]["informativeness"] = {"calls": n, "family": a.family}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(a.out, "calls:", n)


if __name__ == "__main__":
    main()

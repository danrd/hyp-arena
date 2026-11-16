"""Methodological alternatives judged by design (specs/alternatives/design-rule-2026-11-16.yaml): a code verdict from the
registry's design fields against the outside reader's, on pack 22 (in-sample) and pack 6 (independent). Free, no model call.

    python -m scripts.alternatives.design_rule        # -> longevity-kg reviews/argon-2026-11-14/design_rule.json
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from hyparena.card.normalizer import registry_design

KG = Path(__file__).resolve().parents[2].parent / "longevity-kg"
P22, P6 = KG / "reviews" / "argon-2026-11-14", KG / "reviews" / "argon-2026-11-08"
HS = KG / "hypothesis_sources"
ORDER = {"unchanged": 0, "weakened": 1, "eliminated": 2}
KINDS = (     # the first that matches decides
    ("multiplicity", r"multiple (comparisons|test|endpoint|primary)|multiplicity|family-wise|false-positive|statistical independence|independent observations"),
    ("practice", r"practice|familiari[sz]|learning effect|motor learning|test-retest|repeated (test|assess|measure)|retest"),
    ("regression", r"regression to the mean|natural (course|history|recovery)|spontaneous|secular|time trend|seasonal"),
    ("assessor", r"observer|assessor|rater|measurement bias|detection bias|ascertainment|unblinded (outcome|trainer|staff|physio|senior)|charting"),
    ("attention", r"\bcontact\b|attention|supervision|hawthorne|social interaction|staff time"),
    ("expectation", r"expectation|expectanc|placebo|nocebo|unblind|lack of (participant )?blinding|self-report|social desirability|volitional|motivation"),
    ("selection", r"selection|attrition|drop-?out|completers|baseline (imbalance|difference|between)|healthy[- ]user|survivor"),
    ("cointervention", r"adherence|compliance|co-?intervention|concomitant|snacking|carry-?over|washout|vehicle|usual care (drift|change)"),
)


def kind_of(text: str) -> str | None:
    return next((k for k, rx in KINDS if re.search(rx, text, re.I)), None)


def verdict(kind: str, reg: dict) -> str:
    """What the stated design does to a methodological alternative under the expected result, from the registry fields."""
    rand = reg.get("allocation") == "randomized"
    types = [a.get("type") for a in reg.get("arms") or []]
    control = len(types) >= 2 or reg.get("model") in ("parallel", "crossover", "factorial")
    masked = set(reg.get("masked") or [])
    dummy = any(t in ("placebo comparator", "sham comparator") for t in types)
    if kind in ("practice", "regression"):
        return "eliminated" if rand and control else "weakened" if control else "unchanged"
    if kind == "assessor":
        return "eliminated" if "outcomes assessor" in masked else "unchanged"
    if kind == "expectation":
        p = "participant" in masked
        return "eliminated" if p and dummy else "weakened" if p or dummy else "unchanged"
    if kind == "attention":
        return "eliminated" if dummy else "weakened" if "active comparator" in types else "unchanged"
    if kind in ("selection", "cointervention"):
        return "weakened" if rand else "unchanged"
    return "unchanged"


def wkappa(pairs: list[tuple[str, str]]) -> float | None:
    n = len(pairs)
    if n < 2:
        return None
    a, b = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    w = lambda x, y: abs(ORDER[x] - ORDER[y]) / 2
    obs = sum(w(x, y) for x, y in pairs) / n
    exp = sum(a[x] * b[y] * w(x, y) for x in ORDER for y in ORDER) / n / n
    return round(1 - obs / exp, 3) if exp else None


def _summary(rows: list[dict], ours: str, gold: str) -> dict:
    pairs = [(r[ours], r[gold]) for r in rows if r.get(ours) in ORDER and r.get(gold) in ORDER]
    return {"n": len(pairs), "wkappa": wkappa(pairs), "exact": round(sum(x == y for x, y in pairs) / len(pairs), 3) if pairs else None,
            "table": {f"{x} / {y}": c for (x, y), c in sorted(Counter(pairs).items())}}


def pack22() -> dict:
    """In-sample: the outside reader's methodological alternatives of the 30 trials against the code verdict."""
    key = json.loads((P22 / "pack_22_key.json").read_text())
    cards = json.loads((HS / "calibration" / "cards_v3_v17.json").read_text())
    rows = []
    for t in json.loads((P22 / "pack_22_answer.json").read_text())["items"]:
        reg = ((cards.get(key[t["id"]]["unit"]) or {}).get("decisive_experiment") or {}).get("registry") or {}
        for x in t["alternatives"]:
            if x["kind"] != "methodological":
                continue
            k = kind_of(x["statement"])
            rows.append({"trial": t["id"], "rank": x["rank"], "kind": k, "holdout": key[t["id"]]["holdout"],
                         "gold": x["design_on_expected_result"], "code": verdict(k, reg) if k and reg.get("allocation") else None})
    top = [r for r in rows if r["rank"] <= 3]
    return {"methodological": len(rows), "kinds": dict(Counter(r["kind"] or "none of the eight" for r in rows)),
            "coverage_rank_1_3": round(sum(bool(r["kind"]) for r in top) / len(top), 3),
            "all": _summary(rows, "code", "gold"), "holdout": _summary([r for r in rows if r["holdout"]], "code", "gold"),
            "by_kind": {k: _summary([r for r in rows if r["kind"] == k], "code", "gold") for k, _ in KINDS}}


def designs60() -> dict:
    """The registry design fields of the prospective trials (their saved texts were built before the design lines existed)."""
    f = P6 / "pack_6_design_fields.json"
    if f.exists():
        return json.loads(f.read_text())
    from scripts.whole_system.benchmark_run import build_texts
    import tempfile
    us = json.loads((HS / "prospective" / "units_60.json").read_text())
    with tempfile.TemporaryDirectory() as d:
        texts = build_texts([{k: u[k] for k in ("id", "source", "written_on")} for u in us], Path(d) / "t.jsonl")
    out = {t["id"]: registry_design(t["text"]) for t in texts}
    f.write_text(json.dumps(out, indent=1) + "\n")
    return out


def pack6() -> dict:
    """Independent: the outside reader's d for our proposer's alternatives on the prospective trials."""
    key = json.loads((P6 / "pack_6_key.json").read_text())
    run = json.loads((HS / "prospective" / "run_60.json").read_text())
    regs = designs60()
    rows = []
    for t in json.loads((P6 / "pack_6_answer.json").read_text())["trials"]:
        card = (run.get(t["id"]) or {}).get("items", [{}])[0].get("card") or {}
        alts = {a["id"]: a for a in card.get("proposed_alternatives") or []}
        reg = regs.get(t["id"]) or {}
        for x in t["alternatives"]:
            a = alts.get(x["id"])
            if not a or x.get("d_positive") not in ORDER:
                continue
            text = f"{a['subject']['label']} {a['relation']} {a['object']['label']}. {a.get('rationale', '')}"
            k = kind_of(text)
            rows.append({"trial": t["id"], "id": x["id"], "kind": k, "gold": x["d_positive"],
                         "model": (key.get(t["id"], {}).get("alternatives", {}).get(x["id"]) or {}).get("on_positive"),
                         "code": verdict(k, reg) if k and reg.get("allocation") else None})
    classed = [r for r in rows if r["code"]]
    return {"alternatives": len(rows), "classed_with_design_fields": len(classed),
            "kinds": dict(Counter(r["kind"] or "not methodological by the words" for r in rows)),
            "code": _summary(classed, "code", "gold"), "model_on_the_same": _summary(classed, "model", "gold"),
            "model_on_all": _summary(rows, "model", "gold"),
            "by_kind": {k: {"code": _summary([r for r in classed if r["kind"] == k], "code", "gold"),
                            "model": _summary([r for r in classed if r["kind"] == k], "model", "gold")} for k, _ in KINDS}}


def main() -> dict:
    out = {"pack_22_in_sample": pack22(), "pack_6_independent": pack6()}
    (P22 / "design_rule.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    r = main()
    for name, part in r.items():
        print(name, json.dumps({k: v for k, v in part.items() if k != "by_kind"}, indent=None)[:1500])
        for k, v in part["by_kind"].items():
            print("   ", k, json.dumps(v)[:400])

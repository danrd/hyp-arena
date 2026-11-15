"""What the verbatim effect phrase of a record for gives the code (specs/scoring/effect-phrase-2026-11-15.yaml): a count on
the saved runs, outcome links only; free, no model call.

    python -m scripts.reading.effect_phrases        # -> longevity-kg reviews/argon-2026-11-15/effect_phrases.json
"""
from __future__ import annotations

import json
import re
from collections import Counter

from hyparena.reading.effect_class import _FOLD, _RATIO, _SMD, d_from_ci, from_phrase
from scripts.common.v34_check import CAL, PROS

OUT = CAL.parents[1] / "reviews" / "argon-2026-11-15"
RUNS = {"30 trials of pack 18, working reader": [CAL / "run_5_n15x.json"],
        "74 calibration trials, reader v9": [CAL / f"run_{s}_v10.json" for s in (1, 2, 3, 4, 5)],
        "60 prospective trials, reader v9": [PROS / "run_60.json"]}
_CI = re.compile(r"95\s*%\s*(CI|confidence)|\bC\.?I\b", re.I)
_UNIT = r"\d+(\.\d+)?\s*-?\s*(kg|m|s|cm|points?|sec|seconds|ml|mm|g|N|W|kcal|steps|min|m/s|mmHg|mg|years?)\b"


def kind(rec: dict) -> str:
    p = (rec.get("effect_reported") or "").replace("−", "-")
    if rec.get("effect_class") == "none":
        return "null result"
    if not p:
        return "no phrase"
    if _RATIO.search(p) or _FOLD.search(p) or _SMD.search(p):
        return "ratio or standardised difference"
    if d_from_ci(p, rec.get("n_total"), rec.get("comparison")) is not None:
        return "raw difference with its interval, converted"
    if from_phrase(p) != "unclear":
        return "percent or the authors' word"
    if _CI.search(p):
        return "unclear: an interval the parser does not read"
    if not re.search(r"\d", p):
        return "unclear: words only"
    if re.search(r"±|\+/-", p):
        return "unclear: means with their spread"
    if re.search(r"\bfrom\b.*\bto\b|\bvs\.?\b|versus|compared", p, re.I):
        return "unclear: two values"
    if "%" in p:
        return "unclear: a bare percent or share"
    if re.search(r"\bp\s*[<=>≤]", p, re.I) and not re.search(_UNIT, p):
        return "unclear: a p value or test statistic only"
    if re.search(_UNIT, p):
        return "unclear: one difference in units"
    return "unclear: other number"


def main() -> dict:
    out = {}
    for name, files in RUNS.items():
        c = Counter()
        for f in files:
            for r in json.loads(f.read_text()).values():
                it = r["items"][0]
                links = {cl["id"]: cl.get("link") for cl in (it.get("card") or {}).get("claims", [])}
                for cv in (it.get("verification") or {}).get("claims", []):
                    if links.get(cv["id"]) == "outcome":
                        c.update(kind(e) for e in cv.get("evidence", []))
        out[name] = {"records_for_on_outcome_links": sum(c.values()), "kinds": dict(c.most_common())}
    (OUT / "effect_phrases.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, ensure_ascii=False))

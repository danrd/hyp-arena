"""Tests computed from posted group values for ClinicalTrials.gov trials labelled not_reported
(specs/ctgov-outcomes-2026-10-30.yaml: recompute_rules).

    python -m scripts.ctgov_recompute --multi   # second rule: several time points / subscales -> ctgov_recomputed_multi.yaml
    python -m scripts.ctgov_recompute      # writes $KG_DIR/hypothesis_sources/ctgov_recomputed.yaml (no model calls)

Code computes the comparisons; the direction of every significant one is decided by reading the measure description
(field `favours`, filled by hand), and only then are labels changed in ctgov_outcomes.yaml.
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.request

import yaml
from scipy import stats

from scripts.ctgov_outcomes import INPUTS, KG, LABELS

OUT = KG / "hypothesis_sources" / "ctgov_recomputed.yaml"
CONTROL = re.compile(r"placebo|control|sham|usual care|\busual\b|waitlist|wait-list|wait list|standard|no intervention|"
                     r"attention|education", re.I)
MEANS = {"MEAN", "LEAST_SQUARES_MEAN"}
ALPHA = 0.05


def _sd(spread: str, n: int, kind: str, lower: str | None, upper: str | None) -> float | None:
    try:
        if kind == "Standard Deviation":
            return float(spread)
        if kind == "Standard Error":
            return float(spread) * math.sqrt(n)
        if kind.startswith("95%") and lower is not None and upper is not None:
            return (float(upper) - float(lower)) / (2 * 1.96) * math.sqrt(n)
    except (TypeError, ValueError):
        return None
    return None


BASELINE = re.compile(r"baseline|\bpre-|\bpre\b|week 0\b|day 0\b|month 0\b|screening", re.I)


def rows(m: dict) -> list[tuple[str, dict]]:
    """(row title, measurements by group) for every class x category of a measure."""
    out = []
    for cl in m.get("classes") or []:
        for cat in cl.get("categories", []):
            title = " ".join(t for t in (cl.get("title", ""), cat.get("title", "")) if t)
            out.append((title, {x["groupId"]: x for x in cat.get("measurements", [])}))
    return out


def compare(m: dict, multi: bool = False) -> tuple[list[dict], str]:
    """Comparisons of every group with the single control-like group, or ([], reason).
    multi: several rows (time points, subscales) allowed, baseline rows dropped (recompute_rules_multi)."""
    groups = {g["id"]: g.get("title", "") for g in m.get("groups", [])}
    ctrl = [g for g, t in groups.items() if CONTROL.search(t)]
    if len(ctrl) != 1 or len(groups) < 2:
        return [], f"control groups: {len(ctrl)}"
    rs = rows(m)
    if not multi and len(rs) != 1:
        return [], "several classes or categories"
    if multi:
        rs = [r for r in rs if not BASELINE.search(r[0])]
    denoms = (m.get("denoms") or [{}])[0].get("counts", [])
    n = {c["groupId"]: int(float(c["value"])) for c in denoms if c.get("value")}
    c, out = ctrl[0], []
    for row, meas in rs:
        for g in groups:
            if g == c or g not in meas or c not in meas or not n.get(g) or not n.get(c):
                continue
            a, b = meas[g], meas[c]
            try:
                if m.get("paramType") in MEANS:
                    kind = m.get("dispersionType", "")
                    sa = _sd(a.get("spread"), n[g], kind, a.get("lowerLimit"), a.get("upperLimit"))
                    sb = _sd(b.get("spread"), n[c], kind, b.get("lowerLimit"), b.get("upperLimit"))
                    if not sa or not sb:
                        continue
                    t = stats.ttest_ind_from_stats(float(a["value"]), sa, n[g], float(b["value"]), sb, n[c], equal_var=False)
                    p, diff = float(t.pvalue), float(a["value"]) - float(b["value"])
                elif m.get("paramType") == "COUNT_OF_PARTICIPANTS":
                    ka, kb = int(float(a["value"])), int(float(b["value"]))
                    p = float(stats.fisher_exact([[ka, n[g] - ka], [kb, n[c] - kb]])[1])
                    diff = ka / n[g] - kb / n[c]
                else:
                    return [], f"paramType {m.get('paramType')}"
            except (KeyError, TypeError, ValueError):
                continue
            out.append({"row": row, "group": groups[g], "control": groups[c], "diff": round(diff, 4), "p": round(p, 4),
                        "significant": p < ALPHA, "favours": None})
    return out, "" if out else "no computable pair"


def main(multi: bool = False) -> None:
    inputs = {json.loads(l)["nct"]: json.loads(l) for l in INPUTS.read_text().splitlines()}
    labels = yaml.safe_load(LABELS.read_text())["items"]
    todo = [x["nct"] for x in labels if x["label"] == "not_reported" and any(s["id"] == "R" for s in inputs[x["nct"]]["sources"])]
    if multi:   # only the trials the first pass left with several rows
        first = yaml.safe_load(OUT.read_text())["items"]
        todo = [i["nct"] for i in first if i["nct"] in todo and not any(m["comparisons"] for m in i["measures"])
                and any(m["not_computed"] == "several classes or categories" for m in i["measures"])]
    out = []
    for nct in todo:
        d = json.load(urllib.request.urlopen(f"https://clinicaltrials.gov/api/v2/studies/{nct}?fields=ResultsSection", timeout=90))
        time.sleep(0.5)
        item = {"nct": nct, "measures": []}
        for m in (d.get("resultsSection") or {}).get("outcomeMeasuresModule", {}).get("outcomeMeasures", []):
            if m.get("type") != "PRIMARY":
                continue
            comps, why = compare(m, multi)
            item["measures"].append({"title": m.get("title", ""), "description": (m.get("description") or "")[:600],
                                     "paramType": m.get("paramType"), "comparisons": comps, "not_computed": why})
        out.append(item)
    target = OUT.with_name("ctgov_recomputed_multi.yaml") if multi else OUT
    target.write_text(yaml.safe_dump({"items": out}, allow_unicode=True, sort_keys=False, width=200))
    comp = [i for i in out if any(m["comparisons"] for m in i["measures"])]
    sig = [i for i in comp if any(c["significant"] for m in i["measures"] for c in m["comparisons"])]
    print(f"{len(todo)} trials; with a computed comparison {len(comp)}; with a significant one {len(sig)} -> {target}")


if __name__ == "__main__":
    import sys
    main(multi="--multi" in sys.argv)

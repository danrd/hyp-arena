"""Why R2 fell on the current calibration run, and how noisy the evidence balance is (free, no model call; specs/whole-system/
calibration-current-2026-11-16.yaml, result_2026_11_16).

    python -m scripts.whole_system.calibration_r2_diag      # -> calibration/calibration_r2_diag.json

R2 part, for the saved runs (_v10) and the current ones (_cur): a target (a later RCT or meta-analysis of a link) is keyed by
(trial, PMID of the target, side), since link ids differ between card versions. Measures: R2 on the targets of both runs,
each scored from its own run's earlier records (paired); R2 of the current run on targets whose PMID the saved run had read
and on targets new to it; R2 by link kind (outcome or a step before it), by the target's design, by the number of earlier
records; the share of targets "for". Noise part: on the 30 trials of pack 18 read twice before (run_*_n14x reader v16,
run_*_n15x reader v17) and in the current run, Spearman of the balances and the AUC of each, pairwise.
"""
from __future__ import annotations

import importlib
import json
import math
import os
from collections import Counter, defaultdict


def _rows(tag: str) -> list[dict]:
    os.environ["CAL_RUN_TAG"] = tag
    from scripts.common import ablation, v34_check
    importlib.reload(v34_check)
    importlib.reload(ablation)
    from scripts.scoring import record_weight_check as rw
    importlib.reload(rw)
    rows = rw.with_years(rw.pool())
    return [r for r in rows if r["sample"] == "calibration"]


def _targets(rows: list[dict]) -> dict:
    """As record_weight_check.build_refs (R2), keyed by (trial, target PMID, side)."""
    links = defaultdict(list)
    for r in rows:
        links[(r["unit"], r["claim"])].append(r)
    out = {}
    for (unit, claim), rs in links.items():
        dated = [r for r in rs if r["year"]]
        for t in dated:
            if t["dsg"] not in ("rct", "meta_analysis"):
                continue
            prev = [r for r in dated if r["group"] != t["group"] and r["year"] < t["year"]]
            if len(prev) >= 2:
                key = (unit, t["pmid"], t["side"])
                out.setdefault(key, {"label": int(t["side"] == "for"), "records": prev, "link": (unit, claim),
                                     "outcome_link": getattr(t["claim_obj"], "role", None) == "outcome" or t["link"] == "outcome",
                                     "design": t["dsg"]})
    return out


def _score(u) -> float:
    from hyparena.scoring import rules_v32 as r32
    side = {"for": defaultdict(list), "against": defaultdict(list)}
    for r in u["records"]:
        side[r["side"]][r["group"]].append(r32.record_weight_v36(r["rec"], r["claim_obj"], r["side"] == "against"))
    F, A = (sum(max(ws) + r32.FOLD_REST * (sum(ws) - max(ws)) for ws in side[k].values() if ws) for k in ("for", "against"))
    return 1 / (1 + math.exp(-r32.LOGLR_LAMBDA * (F - A)))


def _auc(us: list[dict]) -> dict:
    from scripts.scoring.record_weight_check import auc
    return {"n": len(us), "for": sum(u["label"] for u in us), "auc": auc(us, _score) if us else None}


def r2_part() -> dict:
    old_rows, cur_rows = _rows("_v10"), _rows("_cur")
    old, cur = _targets(old_rows), _targets(cur_rows)
    both = sorted(set(old) & set(cur))
    old_pmids = {(r["unit"], r["pmid"]) for r in old_rows}
    cur_t = list(cur.values())
    return {
        "targets": {"saved": len(old), "current": len(cur), "in_both": len(both)},
        "paired_on_common_targets": {"saved_records": _auc([old[k] for k in both]), "current_records": _auc([cur[k] for k in both])},
        "current_by_origin": {"target_read_by_the_saved_run": _auc([v for k, v in cur.items() if (k[0], k[1]) in old_pmids]),
                              "target_new": _auc([v for k, v in cur.items() if (k[0], k[1]) not in old_pmids])},
        "current_by_link": {"outcome": _auc([u for u in cur_t if u["outcome_link"]]),
                            "step_or_other": _auc([u for u in cur_t if not u["outcome_link"]])},
        "saved_by_link": {"outcome": _auc([u for u in old.values() if u["outcome_link"]]),
                          "step_or_other": _auc([u for u in old.values() if not u["outcome_link"]])},
        "current_by_design": {d: _auc([u for u in cur_t if u["design"] == d]) for d in ("rct", "meta_analysis")},
        "current_by_earlier_records": {"2-4": _auc([u for u in cur_t if len(u["records"]) <= 4]),
                                       "5-9": _auc([u for u in cur_t if 5 <= len(u["records"]) <= 9]),
                                       "10+": _auc([u for u in cur_t if len(u["records"]) >= 10])},
        "targets_per_link_current": dict(sorted(Counter(Counter(u["link"] for u in cur_t).values()).items())),
    }


def _balances(tag: str) -> dict:
    os.environ["CAL_RUN_TAG"] = tag
    from scripts.common import ablation
    importlib.reload(ablation)
    from hyparena.scoring import rules_v32 as r32
    out = {}
    for u in ablation.units():
        e = r32.evaluate(u["card"], u["cvs"], u["alts"], v36=True)
        out[u["id"]] = (-1.0 if e.gate != "pass" else e.chain_state, u["label"])
    return out


def noise_part() -> dict:
    from scipy.stats import spearmanr
    from scripts.common.ablation import auc_of
    b = {t: _balances(t) for t in ("_n14x", "_n15x", "_cur")}
    ids = sorted(set(b["_n14x"]) & set(b["_n15x"]) & set(b["_cur"]))
    out = {"trials": len(ids), "auc": {t: auc_of([b[t][i] for i in ids]) for t in b}}
    for x, y in (("_n14x", "_n15x"), ("_n15x", "_cur"), ("_n14x", "_cur")):
        xs, ys = [b[x][i][0] for i in ids], [b[y][i][0] for i in ids]
        out[f"spearman{x}{y}"] = round(float(spearmanr(xs, ys).statistic), 3)
        out[f"moved_more_than_0.3{x}{y}"] = sum(abs(p - q) > 0.3 for p, q in zip(xs, ys))
    return out


def main() -> dict:
    from scripts.common.ablation import CAL
    res = {"R2": r2_part(), "noise": noise_part()}
    (CAL / "calibration_r2_diag.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    main()

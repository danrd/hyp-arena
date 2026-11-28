"""Component-level judge aggregation and method-vs-judge alignment (`Judge v4` / `Method v4.2`).

Under `docs/method/judge-instructions-v4.md`:
  - Each pair is evaluated independently on four criteria (`grounding`, `novelty`, `benefit`, `testability`).
  - The pair score is computed deterministically by code as the simple equal sum over resolved criteria
    (`+1.0` for `preferred == h`, `+0.5` for `"tie"`, `0.0` for loss).
  - `tiebreak` is inspected strictly as a diagnostic note on pairs whose 4-criterion sum is tied.
  - Primary method validation compares individual method axes against the corresponding judge criteria:
      * `chain_state`               <-> `grounding`
      * `N` (novelty ladder)        <-> `novelty`
      * `(I + feasibility) / 2`     <-> `testability` (plus `I` and `feasibility` separately)
      * `(endpoint + W) / 2`        <-> `benefit`
      * ASPID profile scores        <-> `sum4` (mean of the 4 normalized criterion win rates; diagnostic)

Usage:
    python scripts/calibration/judge_components.py --judge path/to/judge_reconciled.json --results path/to/results.json
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from typing import Optional

CRITERIA = ("grounding", "novelty", "benefit", "testability")
NOV_ORDER = ("unknown", "new_context", "translation", "analog", "new_mechanism", "new_combination", "new_link")
EP_ORDER = (None, "biomarker", "patient_reported", "function", "clinical_event")
W_ORDER = ("local", "organ", "hallmark")


def _rank_ties(vals: list[float]) -> list[float]:
    idx = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    k = 0
    while k < len(vals):
        j = k
        while j + 1 < len(vals) and vals[idx[j + 1]] == vals[idx[k]]:
            j += 1
        avg = (k + j + 2) / 2.0
        for m in range(k, j + 1):
            ranks[idx[m]] = avg
        k = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    rx, ry = _rank_ties(xs), _rank_ties(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 4) if den > 1e-12 else 0.0


def kendall_tau_b(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    conc = disc = tx = ty = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[i] - xs[j]
            dy = ys[i] - ys[j]
            if dx == 0 and dy == 0:
                tx += 1
                ty += 1
            elif dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif dx * dy > 0:
                conc += 1
            else:
                disc += 1
    tot = n * (n - 1) // 2
    den = math.sqrt((tot - tx) * (tot - ty))
    return round((conc - disc) / den, 4) if den > 1e-12 else 0.0


def _extract_pair_ids(pair_obj: dict, blind_key: Optional[dict] = None) -> tuple[str, str]:
    if "hypothesis_ids_forward" in pair_obj and len(pair_obj["hypothesis_ids_forward"]) == 2:
        a, b = pair_obj["hypothesis_ids_forward"]
        return str(a), str(b)
    a = str(pair_obj.get("a") or pair_obj.get("left") or "")
    b = str(pair_obj.get("b") or pair_obj.get("right") or "")
    if blind_key:
        a = str(blind_key.get(a, a))
        b = str(blind_key.get(b, b))
    return a, b


def _extract_criterion_winner(pair_obj: dict, crit: str, a: str, b: str, blind_key: Optional[dict] = None) -> str:
    """Return `a`, `b`, `'tie'`, or `'undetermined'` for one criterion on one pair."""
    if "reconciled" in pair_obj and isinstance(pair_obj["reconciled"], dict):
        w = pair_obj["reconciled"].get(crit)
    else:
        c_obj = (pair_obj.get("criteria") or {}).get(crit)
        w = (c_obj.get("preferred") or c_obj.get("reconciled")) if isinstance(c_obj, dict) else c_obj
    if w is None:
        return "undetermined"
    w_s = str(w).strip()
    if blind_key and w_s in blind_key:
        w_s = str(blind_key[w_s])
    if w_s in (a, "a", "left"):
        return a if w_s != "b" else b
    if w_s in (b, "b", "right"):
        return b
    if w_s.lower() in ("tie", "draw", "split"):
        return "tie"
    return "undetermined"


def score_pair_equal_sum(pair_obj: dict, blind_key: Optional[dict] = None) -> dict:
    """Compute equal-sum pair scores over the 4 independent criteria (`Judge v4`)."""
    a, b = _extract_pair_ids(pair_obj, blind_key)
    sa = sb = 0.0
    resolved = 0
    per_crit: dict[str, str] = {}
    for c in CRITERIA:
        w = _extract_criterion_winner(pair_obj, c, a, b, blind_key)
        per_crit[c] = w
        if w == a:
            sa += 1.0
            resolved += 1
        elif w == b:
            sb += 1.0
            resolved += 1
        elif w == "tie":
            sa += 0.5
            sb += 0.5
            resolved += 1

    if resolved == 0:
        sum_winner = "undetermined"
    elif abs(sa - sb) < 1e-9:
        sum_winner = "tie"
    else:
        sum_winner = a if sa > sb else b

    # Extract diagnostic tiebreak (only meaningful when sum_winner == "tie")
    tb_pref = None
    tb_reason = ""
    tb = pair_obj.get("tiebreak")
    if isinstance(tb, dict):
        raw_p = tb.get("preferred")
        if raw_p:
            tb_pref = str(blind_key.get(str(raw_p), raw_p)) if blind_key else str(raw_p)
        tb_reason = str(tb.get("reason") or "")
    elif sum_winner == "tie" and ("reconciled" in pair_obj or "reconciled_overall" in pair_obj):
        # Legacy v3 fallback: inspect reconciled overall on sum-tied pairs for diagnostic audit
        ov = pair_obj.get("reconciled_overall") or (pair_obj.get("reconciled") or {}).get("overall")
        if ov in (a, b, "tie"):
            tb_pref = ov
        dec = pair_obj.get("pass1_decided_by") or (pair_obj.get("pass_1_forward") or {}).get("decided_by")
        if dec:
            tb_reason = f"legacy_decided_by={dec}"

    return {
        "pair_id": pair_obj.get("pair_id") or f"{a}_vs_{b}",
        "a": a,
        "b": b,
        "criteria": per_crit,
        "resolved_criteria": resolved,
        "score_a": sa,
        "score_b": sb,
        "sum_winner": sum_winner,
        "is_sum_tie": sum_winner == "tie",
        "tiebreak_preferred": tb_pref if sum_winner == "tie" else None,
        "tiebreak_reason": tb_reason if sum_winner == "tie" else "",
    }


def aggregate_judge(judge_data: dict | list, blind_key: Optional[dict] = None) -> dict:
    """Aggregate component win rates, equal-sum standings (`sum4` and `pair_sum_winrate`), and tiebreak diagnostics."""
    pairs_raw = (
        judge_data.get("pairs")
        or judge_data.get("judgements")
        or (judge_data if isinstance(judge_data, list) else [])
    )
    scored_pairs = [score_pair_equal_sum(p, blind_key) for p in pairs_raw]

    hyps_set: set[str] = set()
    for sp in scored_pairs:
        if sp["a"]:
            hyps_set.add(sp["a"])
        if sp["b"]:
            hyps_set.add(sp["b"])
    hyps = sorted(hyps_set)

    pts = {c: defaultdict(float) for c in CRITERIA}
    cnt = {c: defaultdict(int) for c in CRITERIA}
    pair_sum_pts: dict[str, float] = defaultdict(float)
    pair_sum_cnt: dict[str, int] = defaultdict(int)

    for sp in scored_pairs:
        a, b = sp["a"], sp["b"]
        for c in CRITERIA:
            w = sp["criteria"][c]
            if w == a:
                pts[c][a] += 1.0
                cnt[c][a] += 1
                cnt[c][b] += 1
            elif w == b:
                pts[c][b] += 1.0
                cnt[c][a] += 1
                cnt[c][b] += 1
            elif w == "tie":
                pts[c][a] += 0.5
                pts[c][b] += 0.5
                cnt[c][a] += 1
                cnt[c][b] += 1
        sw = sp["sum_winner"]
        if sw == a:
            pair_sum_pts[a] += 1.0
            pair_sum_cnt[a] += 1
            pair_sum_cnt[b] += 1
        elif sw == b:
            pair_sum_pts[b] += 1.0
            pair_sum_cnt[a] += 1
            pair_sum_cnt[b] += 1
        elif sw == "tie":
            pair_sum_pts[a] += 0.5
            pair_sum_pts[b] += 0.5
            pair_sum_cnt[a] += 1
            pair_sum_cnt[b] += 1

    standings: dict[str, dict] = {}
    for h in hyps:
        comp_rates = {
            c: round(pts[c][h] / cnt[c][h], 4) if cnt[c][h] > 0 else 0.0
            for c in CRITERIA
        }
        sum4 = round(sum(comp_rates.values()) / len(CRITERIA), 4)
        p_wr = round(pair_sum_pts[h] / pair_sum_cnt[h], 4) if pair_sum_cnt[h] > 0 else 0.0
        standings[h] = {
            **comp_rates,
            "sum4": sum4,
            "pair_sum_winrate": p_wr,
        }

    sum_ties = [sp for sp in scored_pairs if sp["is_sum_tie"]]
    return {
        "n_pairs": len(scored_pairs),
        "n_hypotheses": len(hyps),
        "n_sum_ties": len(sum_ties),
        "sum_tie_rate": round(len(sum_ties) / len(scored_pairs), 4) if scored_pairs else 0.0,
        "standings": standings,
        "pairs": scored_pairs,
        "tiebreaks": [
            {
                "pair_id": sp["pair_id"],
                "a": sp["a"],
                "b": sp["b"],
                "criteria": sp["criteria"],
                "tiebreak_preferred": sp["tiebreak_preferred"],
                "tiebreak_reason": sp["tiebreak_reason"],
            }
            for sp in sum_ties
        ],
    }


def _ord_frac(val, ladder: tuple) -> float:
    if val not in ladder:
        return 0.0
    return ladder.index(val) / max(len(ladder) - 1, 1)


def compare_with_results(judge_agg: dict, results_data: dict) -> dict:
    """Compute component-by-component rank alignment between `results.json` and `judge_agg`.
    Supports both top-level `calculate.py` output (`{"H01": {"chain_state": ..., "aspid": ...}}`)
    and nested `{"hypotheses": {"H01": {"indicators": ..., "profiles": ...}}}` schemas.
    """
    res_hyps = results_data.get("hypotheses") if isinstance(results_data.get("hypotheses"), dict) else {
        k: v for k, v in results_data.items() if not k.startswith("_") and isinstance(v, dict)
    }
    st = judge_agg["standings"]
    shared = sorted(h for h in st if h in res_hyps and ("indicators" in res_hyps[h] or "chain_state" in res_hyps[h]))
    if len(shared) < 3:
        return {"n_shared": len(shared), "component_alignment": {}, "profile_vs_sum4": {}}

    def _ind(h: str, k: str):
        obj = res_hyps[h]
        if "indicators" in obj and isinstance(obj["indicators"], dict):
            return obj["indicators"].get(k)
        alias = {"N": "novelty", "W": "scope"}.get(k, k)
        return obj.get(alias)

    def _prof_score(h: str, p: str) -> float:
        obj = res_hyps[h]
        if "profiles" in obj and isinstance(obj["profiles"], dict):
            return float(((obj["profiles"].get(p) or {}).get("expected_score")) or 0.0)
        return float((((obj.get("aspid") or {}).get(p) or {}).get("score")) or 0.0)

    pairs_to_check = {
        "chain_state_vs_grounding": (
            [float(_ind(h, "chain_state") or 0.0) for h in shared],
            [st[h]["grounding"] for h in shared],
        ),
        "N_vs_novelty": (
            [_ord_frac(_ind(h, "N") or "unknown", NOV_ORDER) for h in shared],
            [st[h]["novelty"] for h in shared],
        ),
        "testability_composite_vs_testability": (
            [0.5 * float(_ind(h, "I") or 0.0) + 0.5 * float(_ind(h, "feasibility") or 0.0) for h in shared],
            [st[h]["testability"] for h in shared],
        ),
        "I_vs_testability": (
            [float(_ind(h, "I") or 0.0) for h in shared],
            [st[h]["testability"] for h in shared],
        ),
        "feasibility_vs_testability": (
            [float(_ind(h, "feasibility") or 0.0) for h in shared],
            [st[h]["testability"] for h in shared],
        ),
        "benefit_composite_vs_benefit": (
            [
                0.5 * _ord_frac(_ind(h, "endpoint_clinical"), EP_ORDER)
                + 0.5 * _ord_frac(_ind(h, "W") or "local", W_ORDER)
                for h in shared
            ],
            [st[h]["benefit"] for h in shared],
        ),
    }

    comp_align = {
        name: {
            "spearman_rho": spearman(xs, ys),
            "kendall_tau_b": kendall_tau_b(xs, ys),
        }
        for name, (xs, ys) in pairs_to_check.items()
    }

    prof_align = {}
    sum4_vec = [st[h]["sum4"] for h in shared]
    for p in ("evidence", "funding", "frontier", "evolution"):
        p_vec = [_prof_score(h, p) for h in shared]
        if any(abs(v) > 1e-12 for v in p_vec):
            prof_align[p] = {
                "spearman_rho": spearman(p_vec, sum4_vec),
                "kendall_tau_b": kendall_tau_b(p_vec, sum4_vec),
            }

    return {
        "n_shared": len(shared),
        "component_alignment": comp_align,
        "profile_vs_sum4": prof_align,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate Judge v4 component standings and compare with Method results.json.")
    ap.add_argument("--judge", type=Path, required=True, help="Path to judge_reconciled.json or judgements JSON")
    ap.add_argument("--blind-key", type=Path, default=None, help="Optional blind key mapping Bxx -> Hxx")
    ap.add_argument("--results", type=Path, default=None, help="Optional Method results.json for component alignment")
    ap.add_argument("--out", type=Path, default=None, help="Optional output JSON path")
    args = ap.parse_args()

    judge_raw = json.loads(args.judge.read_text(encoding="utf-8"))
    bkey = None
    if args.blind_key and args.blind_key.exists():
        bk_raw = json.loads(args.blind_key.read_text(encoding="utf-8"))
        bkey = bk_raw.get("blind_to_id", bk_raw) if isinstance(bk_raw, dict) else None

    agg = aggregate_judge(judge_raw, bkey)
    out = {"judge_summary": agg}
    if args.results and args.results.exists():
        res_raw = json.loads(args.results.read_text(encoding="utf-8"))
        out["alignment"] = compare_with_results(agg, res_raw)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "judge_summary"} | {
        "n_pairs": agg["n_pairs"],
        "n_sum_ties": agg["n_sum_ties"],
        "sum_tie_rate": agg["sum_tie_rate"],
        "top5_by_sum4": sorted(agg["standings"].items(), key=lambda kv: -kv[1]["sum4"])[:5],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

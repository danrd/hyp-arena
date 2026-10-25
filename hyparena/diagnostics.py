"""Diagnostics of a pool of ranked hypotheses: how many indicators vary, how many pairs a profile orders.

A profile can only order hypotheses by indicators that differ between them. When few indicators vary, or most pairs
sit in groups "on equal footing", the ranking says little however it is weighted: the warning says so instead of
leaving the reader to infer it. The thresholds are defaults (2026-10-23), not results of a calibration."""
from __future__ import annotations

from collections import Counter

MIN_VARYING = 3             # fewer varying indicators than this: warning
MIN_PAIRS_ORDERED = 0.5     # a profile orders fewer pairs than this share: warning
MIN_POOL = 5                # smaller pools are not diagnosed
LEAD_SHARE = 0.8            # one indicator creating this share of the ordered pairs or more: warning


def pairs_ordered(ranking: dict) -> float:
    """Share of pairs not in one group "on equal footing" (the tie rule of the site and the snapshot)."""
    from hyparena.snapshot import places
    K = ranking.get("K") or (ranking.get("meta") or {}).get("K") or 10000
    sizes = Counter(places({"expected": ranking["expected"], "std": ranking.get("std") or {}, "K": K,
                            "order": ranking["order"]}).values())
    n = sum(sizes.values())
    return 1 - sum(v * (v - 1) / 2 for v in sizes.values()) / (n * (n - 1) / 2) if n > 1 else 1.0


def _distinct(values: list) -> int:
    return len({str(v) for v in values if v is not None})


def leading_indicator(ranked: list[dict], ranking: dict, specs: list[str]) -> dict:
    """The indicator that creates the ordered pairs of one profile: every pair in different groups "on equal footing"
    is shared out among the indicators in which its two hypotheses differ (both known and unequal); a pair that
    differs in none (ordered through unknown intervals and weights only) goes to "unknown_only". Returns the
    shares of the ordered pairs per indicator, the leading one and its share."""
    from itertools import combinations

    from hyparena.snapshot import places
    K = ranking.get("K") or (ranking.get("meta") or {}).get("K") or 10000
    group = places({"expected": ranking["expected"], "std": ranking.get("std") or {}, "K": K, "order": ranking["order"]})
    vals = {x["id"]: x["indicators"] for x in ranked}
    ids = [h for h in ranking["order"] if h in vals]
    score, ordered = Counter(), 0
    for a, b in combinations(ids, 2):
        if group[a] == group[b]:
            continue
        ordered += 1
        diff = [i for i in specs if isinstance(vals[a].get(i), (str, int, float)) and isinstance(vals[b].get(i), (str, int, float))
                and vals[a][i] != vals[b][i]]
        for i in diff or ["unknown_only"]:
            score[i] += 1 / (len(diff) or 1)
    shares = {i: round(v / ordered, 3) for i, v in score.most_common()} if ordered else {}
    named = {i: v for i, v in shares.items() if i != "unknown_only"}
    lead = max(named, key=named.get) if named else None
    return {"id": lead, "share": named.get(lead, 0.0) if lead else 0.0, "shares": dict(list(shares.items())[:4]), "ordered_pairs": ordered}


def pool_diagnostics(items: list[dict], rankings: dict, specs: list[str],
                     min_varying: int = MIN_VARYING, min_pairs: float = MIN_PAIRS_ORDERED) -> dict:
    """`items`: dicts with "outcome" and "indicators"; `rankings`: {profile: {"order","expected","std",...}};
    `specs`: ids of the indicators of the run."""
    ranked = [x for x in items if x.get("outcome") == "ranked" and x.get("indicators") is not None]
    varying = [i for i in specs if _distinct([x["indicators"].get(i) for x in ranked]) > 1]
    unknown = [i for i in specs if not any(x["indicators"].get(i) is not None for x in ranked)]
    out = {"ranked": len(ranked), "indicators": len(specs), "varying": varying,
           "constant": [i for i in specs if i not in varying and i not in unknown], "all_unknown": unknown,
           "pairs_ordered": {n: round(pairs_ordered(r), 3) for n, r in rankings.items()}, "warnings": []}
    if len(ranked) < MIN_POOL:
        return out
    out["leading"] = {n: leading_indicator(ranked, r, specs) for n, r in rankings.items()}
    if len(varying) < min_varying:
        out["warnings"].append(f"only {len(varying)} of {len(specs)} indicators differ between the hypotheses "
                               f"(fewer than {min_varying}): the profiles can barely tell them apart")
    one = {n: v for n, v in out["leading"].items() if v["id"] and v["share"] >= LEAD_SHARE}
    if one:
        out["warnings"].append("the order is essentially one indicator: " +
                               ", ".join(f"{n}: {v['id']} makes {v['share']:.0%} of the ordered pairs" for n, v in one.items()))
    low = {n: v for n, v in out["pairs_ordered"].items() if v < min_pairs}
    if low:
        out["warnings"].append("a profile orders fewer than " f"{min_pairs:.0%} of the pairs: " +
                               ", ".join(f"{n} {v:.0%}" for n, v in low.items()))
    return out

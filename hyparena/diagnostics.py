"""Diagnostics of a pool of ranked hypotheses: how many indicators vary, how many pairs a profile orders.

A profile can only order hypotheses by indicators that differ between them. When few indicators vary, or most pairs
sit in groups "on equal footing", the ranking says little however it is weighted: the warning says so instead of
leaving the reader to infer it. The thresholds are defaults (2026-10-23), not results of a calibration."""
from __future__ import annotations

from collections import Counter

MIN_VARYING = 3             # fewer varying indicators than this: warning
MIN_PAIRS_ORDERED = 0.5     # a profile orders fewer pairs than this share: warning
MIN_POOL = 5                # smaller pools are not diagnosed


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
    if len(varying) < min_varying:
        out["warnings"].append(f"only {len(varying)} of {len(specs)} indicators differ between the hypotheses "
                               f"(fewer than {min_varying}): the profiles can barely tell them apart")
    low = {n: v for n, v in out["pairs_ordered"].items() if v < min_pairs}
    if low:
        out["warnings"].append("a profile orders fewer than " f"{min_pairs:.0%} of the pairs: " +
                               ", ".join(f"{n} {v:.0%}" for n, v in low.items()))
    return out

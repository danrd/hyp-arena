"""Which indicators separate the hypotheses of a saved run, how far the profiles pull the order apart, and which
indicators move together. Reads the site bundles (runs/site/*.json); no model calls, nothing is changed.

    python scripts/profile_report.py runs/site/itp2010.json runs/site/evolution.json runs/site/g003.json [--json out.json]
"""
from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.stats import kendalltau, spearmanr

from hyparena.snapshot import places


def _code(spec: dict, v):
    """A number for an indicator value (ordinal: index of the level, worst first; interval: midpoint); None if unknown."""
    if v is None:
        return None
    if spec["kind"] == "ordinal":
        return float(spec["levels"].index(v)) if v in spec["levels"] else None
    return float(sum(v) / 2) if isinstance(v, (list, tuple)) else float(v)


def indicator_table(b: dict, ranked: list[dict]) -> list[dict]:
    rows = []
    for s in b["meta"]["indicators"]:
        vals = [h["indicators"].get(s["id"]) for h in ranked]
        known = [v for v in vals if v is not None]
        c = Counter(map(str, known))
        rows.append({"id": s["id"], "kind": s["kind"], "n": len(vals), "unknown": len(vals) - len(known),
                     "distinct": len(c), "top_value": c.most_common(1)[0] if c else None,
                     "top_share": c.most_common(1)[0][1] / len(known) if known else None,
                     "constant": len(c) <= 1, "counts": dict(c) if s["kind"] == "ordinal" else None})
    return rows


def profile_separation(b: dict, ranked_ids: list[str]) -> dict:
    P, names = b["profiles"], list(b["profiles"])
    out = {"tau": {}, "top3_overlap": {}, "tie_groups": {}, "largest_group": {}, "p_topk_max": {}, "pairs_ordered": {}}
    for a, c in itertools.combinations(names, 2):
        xs = [P[a]["expected"][i] for i in ranked_ids if i in P[a]["expected"] and i in P[c]["expected"]]
        ys = [P[c]["expected"][i] for i in ranked_ids if i in P[a]["expected"] and i in P[c]["expected"]]
        out["tau"][f"{a} / {c}"] = float(kendalltau(xs, ys).statistic)
        out["top3_overlap"][f"{a} / {c}"] = len(set(P[a]["order"][:3]) & set(P[c]["order"][:3]))
    for n in names:
        pl = places(P[n])
        sizes = Counter(pl.values())
        out["tie_groups"][n] = len(sizes)
        out["largest_group"][n] = max(sizes.values())
        out["p_topk_max"][n] = max(P[n]["p_topk"].values())
        m = len(pl)
        out["pairs_ordered"][n] = 1 - sum(v * (v - 1) / 2 for v in sizes.values()) / (m * (m - 1) / 2) if m > 1 else 0.0
    return out


def correlations(b: dict, ranked: list[dict]) -> dict:
    specs = [s for s in b["meta"]["indicators"]]
    X = {s["id"]: np.array([np.nan if (c := _code(s, h["indicators"].get(s["id"]))) is None else c for h in ranked]) for s in specs}
    pairs = []
    for a, c in itertools.combinations(X, 2):
        ok = ~np.isnan(X[a]) & ~np.isnan(X[c])
        if ok.sum() >= 8 and np.ptp(X[a][ok]) > 0 and np.ptp(X[c][ok]) > 0:
            r = float(spearmanr(X[a][ok], X[c][ok]).statistic)
            pairs.append({"a": a, "b": c, "rho": r, "n": int(ok.sum())})
    drivers = {}
    for n, P in b["profiles"].items():
        E = np.array([P["expected"].get(h["id"], np.nan) for h in ranked])
        drivers[n] = {}
        for s in specs:
            ok = ~np.isnan(X[s["id"]]) & ~np.isnan(E)
            if ok.sum() >= 8 and np.ptp(X[s["id"]][ok]) > 0:
                drivers[n][s["id"]] = float(spearmanr(X[s["id"]][ok], E[ok]).statistic)
    return {"pairs": sorted(pairs, key=lambda p: -abs(p["rho"])), "drivers": drivers}


def _aggregate(b: dict, ranked: list[dict], profile: str, drop: tuple[str, ...] = (), K: int = 10000):
    """The ranking of the ranked hypotheses recomputed from the bundle's indicator values (no model calls), without the
    indicators in `drop`; with drop=() it must reproduce the bundle's own ranking."""
    from dataclasses import replace

    from hyparena.aspid import aggregate, load_profiles
    from hyparena.card.indicators import for_meta
    BY_ID = {s.id: s for s in for_meta(b["meta"])}              # the run's own set and levels
    keep = [s["id"] for s in b["meta"]["indicators"] if s["id"] not in drop]
    tiers = [t if isinstance(t, str) else [i for i in t if i in keep] for t in b["meta"]["profiles"][profile]["tiers"]]
    prof = replace(load_profiles()[profile], tiers=[t for t in tiers if t])
    values = {h["id"]: {i: h["indicators"].get(i) for i in keep} for h in ranked}
    return aggregate(values, [BY_ID[i] for i in keep], prof, K=K, seed=0, k_top=b["meta"].get("k_top", 3))


def ablation(b: dict, ranked: list[dict], profile: str = "evidence_first") -> dict:
    """What leaving out one indicator does to the order (Kendall tau of the expected values against the full ranking, the
    top 3 kept, the share of pairs ordered). Not scored against any label."""
    full = _aggregate(b, ranked, profile)
    ids = [h["id"] for h in ranked]
    out = {"same_as_bundle": float(kendalltau([full.expected[i] for i in ids],
                                              [b["profiles"][profile]["expected"][i] for i in ids]).statistic), "drop": {}}
    for ind in [s["id"] for s in b["meta"]["indicators"]]:
        try:
            r = _aggregate(b, ranked, profile, (ind,))
        except (ValueError, KeyError) as e:
            out["drop"][ind] = {"error": str(e)[:60]}
            continue
        pl = places({"expected": r.expected, "std": r.std, "K": 10000, "order": r.order})
        sizes = Counter(pl.values())
        out["drop"][ind] = {"tau": float(kendalltau([full.expected[i] for i in ids], [r.expected[i] for i in ids]).statistic),
                            "top3_kept": len(set(full.order[:3]) & set(r.order[:3])),
                            "pairs_ordered": 1 - sum(v * (v - 1) / 2 for v in sizes.values()) / (len(pl) * (len(pl) - 1) / 2)}
    return out


def report(path: str, ablate: bool = True) -> dict:
    b = json.loads(Path(path).read_text())
    ranked = [h for h in b["hypotheses"] if h["outcome"] == "ranked"]
    return {"bundle": path, "title": b["title"], "n": len(b["hypotheses"]), "ranked": len(ranked),
            "diagnostics": b["meta"].get("diagnostics"), "indicators": indicator_table(b, ranked), "profiles": profile_separation(b, [h["id"] for h in ranked]),
            "correlations": correlations(b, ranked),
            "ablation": {n: ablation(b, ranked, n) for n in ("evidence_first", "fundamental")} if ablate else {}, "mc_halfwidth": next(iter(b["profiles"].values())).get("mc_halfwidth")}


def show(r: dict) -> None:
    print(f"\n## {r['title']}  ({r['bundle']}): {r['ranked']} ranked of {r['n']}")
    d = r.get("diagnostics")
    if d:
        print(f"Pool diagnostics: {len(d['varying'])} of {d['indicators']} indicators vary; constant: {', '.join(d['constant']) or '-'}; "
              f"unknown for all: {', '.join(d['all_unknown']) or '-'}; pairs ordered: "
              + ", ".join(f"{n} {v:.0%}" for n, v in d["pairs_ordered"].items()))
        for n, v in (d.get("leading") or {}).items():
            print(f"  leading indicator, {n}: {v['id']} ({v['share']:.0%} of {v['ordered_pairs']} ordered pairs); shares {v['shares']}")
        for w in d["warnings"]:
            print(f"  WARNING: {w}")
    print("\nIndicators over the ranked hypotheses")
    print(f"{'indicator':<20}{'unknown':>8}{'distinct':>9}  most common value")
    for x in r["indicators"]:
        top = f"{x['top_value'][0]} ({x['top_share']:.0%})" if x["top_value"] else "-"
        print(f"{x['id']:<20}{x['unknown']:>8}{x['distinct']:>9}  {top}{'  CONSTANT' if x['constant'] else ''}")
    p = r["profiles"]
    print("\nProfiles: Kendall tau of the expected values, overlap of the top 3, tie groups, largest group, max P(top-3), share of pairs the profile orders (not 'on equal footing')")
    for k in p["tau"]:
        print(f"  {k:<36} tau {p['tau'][k]:.2f}  top-3 overlap {p['top3_overlap'][k]}")
    for n in p["tie_groups"]:
        print(f"  {n:<18} groups {p['tie_groups'][n]:>3} of {r['ranked'] + 0}  largest {p['largest_group'][n]:>3}  max P(top-3) {p['p_topk_max'][n]:.2f}  pairs ordered {p['pairs_ordered'][n]:.0%}")
    print("\nIndicators that move together (Spearman, |rho| >= 0.5)")
    for q in r["correlations"]["pairs"]:
        if abs(q["rho"]) >= 0.5:
            print(f"  {q['a']:<20}{q['b']:<20} rho {q['rho']:+.2f}  n={q['n']}")
    print("\nIndicators against the expected value of each profile (Spearman)")
    for n, d in r["correlations"]["drivers"].items():
        print(f"  {n:<16}" + "  ".join(f"{k} {v:+.2f}" for k, v in sorted(d.items(), key=lambda t: -abs(t[1]))[:6]))


def show_ablation(r: dict) -> None:
    for n, a in r["ablation"].items():
        print(f"\nLeave one indicator out, profile {n} (recomputed from the bundle: tau {a['same_as_bundle']:.3f} against its own ranking)")
        for ind, v in a["drop"].items():
            if "error" in v:
                print(f"  without {ind:<20} {v['error']}")
            else:
                print(f"  without {ind:<20} tau {v['tau']:.2f}  top-3 kept {v['top3_kept']}  pairs ordered {v['pairs_ordered']:.0%}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("bundles", nargs="+")
    ap.add_argument("--json", default=None)
    ap.add_argument("--no-ablation", action="store_true", help="skip the leave-one-indicator-out recomputation")
    a = ap.parse_args()
    out = [report(p, not a.no_ablation) for p in a.bundles]
    for r in out:
        show(r)
        show_ablation(r)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

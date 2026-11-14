"""ASPID aggregation calibration by simulation (check if p_topk is calibrated)."""
import argparse
import csv
from typing import Any, Optional

import numpy as np

from hyparena.aspid import IndicatorSpec, Profile, WeightSampler, _ordinal_mapping, aggregate, load_profiles
from hyparena.card.indicators import INDICATORS, BY_ID

def _get_profile_indicators(profile: Profile) -> list[IndicatorSpec]:
    """Return the indicator specs used by the profile."""
    # Find all indicator IDs referenced in the profile tiers
    ids = set()
    for t in profile.tiers:
        if t != "rest":
            ids.update(t)
    for eq in profile.equal:
        ids.update(eq)
    if "rest" in profile.tiers:
        ids.update(s.id for s in INDICATORS)
    # If a profile doesn't have tiers/equal, it might just use all
    if not profile.tiers and not profile.equal:
        ids.update(s.id for s in INDICATORS)

    return [s for s in INDICATORS if s.id in ids]       # the order of INDICATORS: a set of strings iterates differently in every process

def _generate_data(
    m: int,
    indicators: list[IndicatorSpec],
    data_rng: np.random.Generator,
    unknown_share: float
) -> tuple[dict[str, dict[str, Any]], np.ndarray]:
    """Draw random indicator values and their true mapped values for m hypotheses."""
    values: dict[str, dict[str, Any]] = {}
    true_q = np.zeros((m, len(indicators)))

    for i in range(m):
        h_id = f"H-{i+1}"
        values[h_id] = {}
        for j, s in enumerate(indicators):
            is_unknown = data_rng.random() < unknown_share

            if s.kind == "ordinal":
                if is_unknown:
                    values[h_id][s.id] = None
                    true_lvl_idx = data_rng.integers(0, len(s.levels))
                else:
                    true_lvl_idx = data_rng.integers(0, len(s.levels))
                    values[h_id][s.id] = s.levels[true_lvl_idx]

                mapping = _ordinal_mapping(len(s.levels), s.mapping, 1, data_rng)
                true_q[i, j] = mapping[0, true_lvl_idx]
            else:
                if is_unknown:
                    values[h_id][s.id] = None
                    true_val_raw = s.bounds[0] + data_rng.random() * (s.bounds[1] - s.bounds[0])
                    true_q[i, j] = s.scale(true_val_raw)
                else:
                    val_raw = s.bounds[0] + data_rng.random() * (s.bounds[1] - s.bounds[0])
                    values[h_id][s.id] = val_raw
                    true_q[i, j] = s.scale(val_raw)

    return values, true_q

def run_calibration(
    profile_name: str,
    m: int,
    worlds: int,
    K: int,
    k_top: int,
    seed: int,
    out_csv: Optional[str],
    random_mapping: bool,
    unknown_share: float = 0.0
) -> tuple[float, float, list[dict[str, Any]], np.ndarray]:
    """Run calibration simulation over multiple worlds."""
    profiles = load_profiles()
    profile = profiles[profile_name]

    base_indicators = _get_profile_indicators(profile)

    indicators = []
    for ind in base_indicators:
        mapping = ind.mapping
        if not random_mapping and ind.kind == "ordinal":
            mapping = "equal_steps"

        new_ind = IndicatorSpec(
            id=ind.id,
            kind=ind.kind,
            levels=ind.levels,
            bounds=ind.bounds,
            log=ind.log,
            higher_is_better=ind.higher_is_better,
            mapping=mapping,
            note=ind.note
        )
        indicators.append(new_ind)

    rng = np.random.default_rng(seed)
    sampler = WeightSampler([s.id for s in indicators], profile)
    true_weights_all = sampler.sample(worlds, rng)

    results = []
    for w_idx in range(worlds):
        true_w = true_weights_all[w_idx]
        data_rng = np.random.default_rng(seed + 1000 + w_idx)

        values, true_q = _generate_data(m, indicators, data_rng, unknown_share)

        true_utilities = true_q @ true_w
        tie = data_rng.random(m) * 1e-12
        ranks = (-(true_utilities + tie)).argsort().argsort()
        is_topk = (ranks < k_top)

        res = aggregate(values, indicators, profile, K=K, seed=seed + 2000 + w_idx, k_top=k_top)

        for i in range(m):
            h_id = f"H-{i+1}"
            p_topk = res.p_topk.get(h_id, 0.0)
            results.append({
                "world": w_idx,
                "hypothesis": h_id,
                "p_topk": p_topk,
                "is_topk": int(is_topk[i])
            })

    bins = np.linspace(0, 1, 11)

    print("Calibration Table:")
    print(f"{'Bin':<15} | {'Mean Pred':<10} | {'Obs Share':<10} | {'Count':<10}")

    ece = 0.0
    brier = 0.0

    for b_idx in range(len(bins)-1):
        low, high = bins[b_idx], bins[b_idx+1]

        if b_idx == len(bins) - 2:
            mask = [r for r in results if low <= r["p_topk"] <= high]
        else:
            mask = [r for r in results if low <= r["p_topk"] < high]

        count = len(mask)
        if count > 0:
            mean_pred = sum(r["p_topk"] for r in mask) / count
            obs_share = sum(r["is_topk"] for r in mask) / count
            print(f"{low:.2f}-{high:.2f}         | {mean_pred:.4f}     | {obs_share:.4f}     | {count}")
            ece += (count / len(results)) * abs(mean_pred - obs_share)

            for r in mask:
                brier += (r["p_topk"] - r["is_topk"]) ** 2

    brier /= len(results)
    print(f"\nExpected Calibration Error (ECE): {ece:.4f}")
    print(f"Brier Score: {brier:.4f}")

    if out_csv:
        with open(out_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["world", "hypothesis", "p_topk", "is_topk"])
            writer.writeheader()
            writer.writerows(results)

    return ece, brier, results, bins

def main() -> None:
    """Parse args and run calibration."""
    parser = argparse.ArgumentParser(description="ASPID Calibration by Simulation")
    parser.add_argument("profile", help="Profile name")
    parser.add_argument("--m", type=int, default=10, help="Number of hypotheses")
    parser.add_argument("--worlds", type=int, default=100, help="Number of simulated worlds")
    parser.add_argument("--K", type=int, default=2000, help="K per world")
    parser.add_argument("--k-top", type=int, default=3, help="k_top")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--out", type=str, required=True, help="Output CSV path")
    parser.add_argument("--random-mapping", action="store_true", help="Use random ordinal mappings")
    parser.add_argument("--unknown-share", type=float, default=0.0, help="Share of unknown values")
    args = parser.parse_args()

    run_calibration(
        args.profile,
        args.m,
        args.worlds,
        args.K,
        args.k_top,
        args.seed,
        args.out,
        args.random_mapping,
        args.unknown_share
    )

if __name__ == "__main__":
    main()

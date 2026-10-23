import argparse
import math
import numpy as np
from scipy.stats import kendalltau
from dataclasses import replace
from hyparena.aspid import IndicatorSpec, aggregate, Profile, load_profiles
from hyparena.card.indicators import INDICATORS

def _generate_random_pool(n_hypotheses: int, rng: np.random.Generator, specs: list[IndicatorSpec]) -> dict[str, dict[str, object]]:
    """Generates a random pool of hypotheses with values for the given indicators."""
    pool = {}
    for i in range(n_hypotheses):
        h_id = f"H{i}"
        vals = {}
        for s in specs:
            if s.kind == "ordinal":
                vals[s.id] = rng.choice(s.levels)
            elif s.kind == "cardinal":
                # Assuming bounds are finite for random generation
                lo, hi = s.bounds
                if lo is None: lo = 0.0
                if hi is None: hi = 100.0
                vals[s.id] = float(rng.uniform(lo, hi))
        pool[h_id] = vals
    return pool

def compute_sensitivity(pool: dict[str, dict[str, object]], profile: Profile, k: int = 10000, seed: int = 42) -> tuple[float, float, float]:
    """Computes Kendall tau-b between SMAA-O ordinal mapping and equal_steps mapping, along with bootstrap interval."""
    # Run with default mapping (SMAA-O / random)
    res_default = aggregate(pool, INDICATORS, profile, K=k, seed=seed)

    # Run with equal_steps mapping. Note IndicatorSpec is frozen, so we use replace.
    specs_equal_steps = []
    for s in INDICATORS:
        if s.kind == "ordinal":
            specs_equal_steps.append(replace(s, mapping="equal_steps"))
        else:
            specs_equal_steps.append(s)

    res_equal_steps = aggregate(pool, specs_equal_steps, profile, K=k, seed=seed)

    # Compute Kendall tau-b
    expected_default = [res_default.expected[h] for h in pool]
    expected_equal_steps = [res_equal_steps.expected[h] for h in pool]
    tau, _ = kendalltau(expected_default, expected_equal_steps)

    # Bootstrap interval for tau
    n_boot = 1000
    rng = np.random.default_rng(seed + 1)
    taus = []
    n_items = len(pool)
    for _ in range(n_boot):
        idx = rng.integers(0, n_items, size=n_items)
        # Resample expected values pairs
        exp1_boot = [expected_default[i] for i in idx]
        exp2_boot = [expected_equal_steps[i] for i in idx]
        t, _ = kendalltau(exp1_boot, exp2_boot)
        if not math.isnan(t):
            taus.append(t)

    if taus:
        ci_lower = np.percentile(taus, 2.5)
        ci_upper = np.percentile(taus, 97.5)
    else:
        ci_lower, ci_upper = tau, tau

    return tau, ci_lower, ci_upper

def main():
    parser = argparse.ArgumentParser(description="Sensitivity analysis of ASPID aggregation for ordinal mappings.")
    parser.add_argument("--pool-size", type=int, default=20, help="Number of hypotheses in the random pool.")
    parser.add_argument("--k", type=int, default=10000, help="Number of MC iterations.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    pool = _generate_random_pool(args.pool_size, rng, INDICATORS)
    profiles = load_profiles()

    print(f"Sensitivity Analysis (Kendall tau-b between default mapping and equal_steps)")
    print(f"Pool Size: {args.pool_size}, K: {args.k}, Seed: {args.seed}")
    print("-" * 60)
    for name, prof in profiles.items():
        tau, ci_low, ci_high = compute_sensitivity(pool, prof, args.k, args.seed)
        print(f"Profile {name:20}: tau = {tau:.3f} [{ci_low:.3f}, {ci_high:.3f}]")

if __name__ == "__main__":
    main()

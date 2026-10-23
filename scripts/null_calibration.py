#!/usr/bin/env python3
import argparse
import csv
import sys

import numpy as np
import scipy.stats.distributions as dist

from hyparena.tools.survival import logrank_test, permutation_null


def simulate_dataset(n_per_group: int, hr: float, censor_rate: float, rng: np.random.Generator):
    times_0 = rng.exponential(scale=1.0, size=n_per_group)
    times_1 = rng.exponential(scale=1.0 / hr, size=n_per_group)

    times = np.concatenate([times_0, times_1])
    groups = np.concatenate([np.zeros(n_per_group), np.ones(n_per_group)])

    # Type I censoring yielding approximate censor_rate
    C = -np.log(censor_rate) if censor_rate > 0 else np.inf

    observed_times = np.minimum(times, C)
    events = (times <= C).astype(int)

    return observed_times, events, groups


def main():
    parser = argparse.ArgumentParser(description="Null calibration and power check for log-rank test.")
    parser.add_argument("--n-per-group", type=int, default=40, help="Samples per group (default 40)")
    parser.add_argument("--censor-rate", type=float, default=0.3, help="Censoring share (default 0.3)")
    parser.add_argument("--hr-list", type=str, default="1.0,1.3,1.6,2.0", help="Comma-separated list of hazard ratios")
    parser.add_argument("--n-datasets", type=int, default=500, help="Number of datasets to simulate per HR (default 500)")
    parser.add_argument("--alpha", type=float, default=0.05, help="Alpha level (default 0.05)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42)")
    parser.add_argument("--out", type=str, help="Output CSV path")
    parser.add_argument("--permutation", action="store_true", help="Use permutation null instead of asymptotic chi2")

    args = parser.parse_args()

    hrs = [float(x.strip()) for x in args.hr_list.split(",")]
    rng = np.random.default_rng(args.seed)

    results = []

    print(f"{'HR':<6} | {'Rejection Rate':<15} | {'95% Interval'}")
    print("-" * 45)

    for hr in hrs:
        rejections = 0
        for _ in range(args.n_datasets):
            t, e, g = simulate_dataset(args.n_per_group, hr, args.censor_rate, rng)

            if args.permutation:
                chi2_nulls = permutation_null(t, e, g, n_perm=1000, rng=rng)
                res = logrank_test(t, e, g)
                p_val = np.mean(chi2_nulls >= res.chi2)
            else:
                res = logrank_test(t, e, g)
                p_val = res.p_value

            if p_val < args.alpha:
                rejections += 1

        rate = rejections / args.n_datasets
        # 95% Clopper-Pearson or asymptotic interval.
        # Using scipy.stats.binom.interval(0.95, n, p) where p=rate gives interval for observed rate,
        # but we need the confidence interval for the true probability.
        # Alternatively, asymptotic: p +/- 1.96 * sqrt(p*(1-p)/n)
        se = np.sqrt(rate * (1 - rate) / args.n_datasets)
        lower = max(0.0, rate - 1.96 * se)
        upper = min(1.0, rate + 1.96 * se)

        print(f"{hr:<6.1f} | {rate:<15.3f} | [{lower:.3f}, {upper:.3f}]")
        results.append({"hr": hr, "rejection_rate": rate, "lower_95": lower, "upper_95": upper})

    if args.out:
        with open(args.out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["hr", "rejection_rate", "lower_95", "upper_95"])
            writer.writeheader()
            writer.writerows(results)

if __name__ == "__main__":
    main()

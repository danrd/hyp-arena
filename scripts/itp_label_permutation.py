"""Permutation test for the ITP-2010 backtest primary metric.

Reads a snapshot CSV, extracts the ranked items, their labels and expected scores,
and computes the observed AUC and the label-permutation null distribution.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from hyparena.backtest import tied_auc


def get_auc_variants(labels: np.ndarray, expected: np.ndarray, tol: float = 0.002) -> tuple[float, float]:
    """Compute observed AUC in two variants: (a) plain Mann-Whitney with ties counted half,
    (b) ties = |dE| < tol counted half.
    """
    pos = expected[labels == 1.0]
    neg = expected[labels == 0.0]

    if len(pos) == 0 or len(neg) == 0:
        return float("nan"), float("nan")

    pos_mat = pos[:, np.newaxis]
    neg_mat = neg[np.newaxis, :]

    diff = pos_mat - neg_mat

    auc_plain = (np.sum(diff > 0) + 0.5 * np.sum(diff == 0)) / (len(pos) * len(neg))
    auc_tol = (np.sum(diff > tol) + 0.5 * np.sum(np.abs(diff) <= tol)) / (len(pos) * len(neg))

    return auc_plain, auc_tol


def compute_observed_auc(labels: np.ndarray, expected: np.ndarray, tol: float, std: np.ndarray | None, K: int | None) -> float:
    """Computes the primary observed AUC. If std and K are present, uses tied_auc, otherwise tol-based AUC."""
    if std is not None and K is not None:
        pos = [(expected[i], std[i]) for i in range(len(labels)) if labels[i] == 1.0]
        neg = [(expected[i], std[i]) for i in range(len(labels)) if labels[i] == 0.0]
        return tied_auc(pos, neg, K)

    _, auc_tol = get_auc_variants(labels, expected, tol)
    return auc_tol


def bootstrap_auc_self_contained(labels: np.ndarray, expected: np.ndarray, tol: float, std: np.ndarray | None, K: int | None, n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """Bootstrap confidence interval for the AUC over items, self-contained."""
    rng = np.random.default_rng(seed)
    pos_idx = np.where(labels == 1.0)[0]
    neg_idx = np.where(labels == 0.0)[0]

    if len(pos_idx) == 0 or len(neg_idx) == 0:
        return float("nan"), float("nan")

    aucs = []
    for _ in range(n_boot):
        p_boot = rng.choice(pos_idx, size=len(pos_idx), replace=True)
        n_boot_idx = rng.choice(neg_idx, size=len(neg_idx), replace=True)
        boot_labels = np.concatenate([np.ones(len(pos_idx)), np.zeros(len(neg_idx))])
        boot_expected = np.concatenate([expected[p_boot], expected[n_boot_idx]])

        boot_std = None
        if std is not None:
            boot_std = np.concatenate([std[p_boot], std[n_boot_idx]])

        aucs.append(compute_observed_auc(boot_labels, boot_expected, tol, boot_std, K))

    aucs.sort()
    return aucs[int(0.025 * n_boot)], aucs[int(0.975 * n_boot) - 1]


def permutation_test(labels: np.ndarray, expected: np.ndarray, tol: float, std: np.ndarray | None, K: int | None, n_perm: int, seed: int) -> dict[str, Any]:
    """Permute labels n times and return the null mean, 2.5/97.5 percentiles, and p-value."""
    obs_auc = compute_observed_auc(labels, expected, tol, std, K)

    rng = np.random.default_rng(seed)

    pos_count = int(np.sum(labels))
    neg_count = len(labels) - pos_count

    # Vectorized AUC computation over permutations is feasible but might be tricky
    # with the custom tied_auc which takes lists of tuples.
    # To keep it completely vectorized in numpy for both variants:
    # We can precompute a pairwise score comparison matrix.

    null_aucs = np.zeros(n_perm)

    if std is not None and K is not None:
        # Build pairwise matrix for tied_auc explicitly using the function logic to guarantee sync
        # Since it only depends on pairs of (expected, std), we can do this fast in Python loops just once (N*N).
        # We need tied_auc((a_exp, a_std), (b_exp, b_std)) which evaluates one pair.
        # tied_auc expects lists. For one pair, pos is one item, neg is one item.
        n_items = len(expected)
        score_mat = np.zeros((n_items, n_items))
        for i in range(n_items):
            for j in range(n_items):
                score_mat[i, j] = tied_auc([(expected[i], std[i])], [(expected[j], std[j])], K)
    else:
        expected_mat_diff = expected[:, np.newaxis] - expected[np.newaxis, :]
        score_mat = np.zeros((len(expected), len(expected)))
        score_mat[expected_mat_diff > tol] = 1.0
        score_mat[expected_mat_diff < -tol] = 0.0
        score_mat[(expected_mat_diff <= tol) & (expected_mat_diff >= -tol)] = 0.5

    # Each permutation is just a random shuffling of the labels.
    # We can generate a matrix of permuted labels: shape (n_perm, len(labels))
    permuted_labels = np.zeros((n_perm, len(labels)))
    for i in range(n_perm):
        permuted_labels[i] = rng.permutation(labels)

    for i in range(n_perm):
        p_mask = permuted_labels[i] == 1.0
        n_mask = permuted_labels[i] == 0.0

        # Select submatrix of score_mat
        submat = score_mat[np.ix_(p_mask, n_mask)]
        null_aucs[i] = np.sum(submat) / (pos_count * neg_count)

    null_mean = np.mean(null_aucs)
    sorted_null = np.sort(null_aucs)
    perc_025 = sorted_null[int(0.025 * n_perm)]
    perc_975 = sorted_null[int(0.975 * n_perm) - 1] if n_perm > 0 else 0.0

    count_ge = np.sum(null_aucs >= obs_auc)
    p_value = (count_ge + 1) / (n_perm + 1)

    return {
        "observed_auc": obs_auc,
        "null_mean": float(null_mean),
        "null_2.5": float(perc_025),
        "null_97.5": float(perc_975),
        "p_value": float(p_value)
    }


def load_data(snapshot_path: str, bundle_path: str | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, int | None]:
    """Load items from the snapshot where outcome is 'ranked'.
    Returns labels (1 for 'supports', 0 otherwise), expected scores,
    and optional standard deviations and K if a bundle is provided.
    """
    labels_list = []
    expected_list = []
    ids = []

    with open(snapshot_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("outcome") == "ranked":
                labels_list.append(1.0 if row.get("later_label") == "supports" else 0.0)
                expected_list.append(float(row["expected"]))
                ids.append(row["id"])

    labels = np.array(labels_list)
    expected = np.array(expected_list)

    std = None
    K = None
    if bundle_path:
        bundle = json.loads(Path(bundle_path).read_text())
        prof = bundle.get("profiles", {}).get("evidence_first", {})
        stds = prof.get("std", {})
        std_list = [stds.get(i, 0.0) for i in ids]
        std = np.array(std_list)
        K = bundle.get("K")

    return labels, expected, std, K


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", help="Path to the snapshot CSV (e.g. tests/fixtures/itp2010_snapshot.csv)")
    parser.add_argument("--bundle", default=None, help="Optional path to site bundle JSON for std and K")
    parser.add_argument("--tol", type=float, default=0.002, help="Tolerance for score ties (default: 0.002)")
    parser.add_argument("--n", type=int, default=10000, help="Number of permutations (default: 10000)")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for permutations (default: 0)")
    parser.add_argument("--out", default=None, help="Optional path to output JSON results")
    args = parser.parse_args()

    labels, expected, std, K = load_data(args.snapshot, args.bundle)

    auc_plain, auc_tol = get_auc_variants(labels, expected, args.tol)
    obs_auc = compute_observed_auc(labels, expected, args.tol, std, K)

    boot_lo, boot_hi = bootstrap_auc_self_contained(labels, expected, args.tol, std, K)

    base_rate = np.mean(labels)

    perm_res = permutation_test(labels, expected, args.tol, std, K, args.n, args.seed)

    res = {
        "base_rate": float(base_rate),
        "plain_auc": float(auc_plain),
        "observed_tied_auc": float(obs_auc),
        "bootstrap_95ci": [float(boot_lo), float(boot_hi)],
        "permutation_null": {
            "n": args.n,
            "mean": perm_res["null_mean"],
            "2.5_percentile": perm_res["null_2.5"],
            "97.5_percentile": perm_res["null_97.5"],
            "p_value": perm_res["p_value"]
        }
    }

    print(f"Base rate: {base_rate:.4f}")
    print(f"Plain AUC: {auc_plain:.4f}")
    print(f"Observed Tied AUC: {obs_auc:.4f} (95% CI: {boot_lo:.4f} - {boot_hi:.4f})")
    print(f"Permutation test ({args.n} perms):")
    print(f"  Null mean: {perm_res['null_mean']:.4f}")
    print(f"  Null 95% interval: {perm_res['null_2.5']:.4f} - {perm_res['null_97.5']:.4f}")
    print(f"  p-value: {perm_res['p_value']:.4e}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()

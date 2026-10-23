"""Metrics for the benchmark that ranks hypotheses and compares rankers.
Contains evaluation metrics and bootstrap intervals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

import numpy as np
import scipy.stats


def auc(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Area under the ROC curve for binary labels (1 = positive), ties get half credit (Mann-Whitney form)."""
    scores_arr = np.asarray(scores)
    labels_arr = np.asarray(labels)
    n_pos = np.sum(labels_arr == 1)
    n_neg = np.sum(labels_arr == 0)
    if n_pos == 0 or n_neg == 0:
        raise ValueError("AUC requires both positive and negative classes.")

    ranks = scipy.stats.rankdata(scores_arr)
    pos_ranks = ranks[labels_arr == 1]

    u1 = np.sum(pos_ranks) - n_pos * (n_pos + 1) / 2
    return float(u1 / (n_pos * n_neg))


def precision_at_k(scores: Sequence[float], labels: Sequence[int], k: int) -> float:
    """Share of positives among the k highest scores. Ties are broken by input order (stable sort)."""
    scores_arr = np.asarray(scores)
    labels_arr = np.asarray(labels)

    # We want to select the k largest scores, with ties broken by input order.
    # Argsort normally sorts ascending, and is stable.
    # To sort descending while keeping ties stable by original order:
    # We can argsort the negated scores, but numpy's stable sort with duplicate negative scores
    # will keep them in original order.
    idx = np.argsort(-scores_arr, kind='stable')
    top_k_labels = labels_arr[idx[:k]]
    return float(np.mean(top_k_labels == 1))


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman rank correlation."""
    res = scipy.stats.spearmanr(x, y)
    return float(res.statistic)


def kendall_tau(x: Sequence[float], y: Sequence[float]) -> float:
    """Kendall tau-b rank correlation (ties handled)."""
    res = scipy.stats.kendalltau(x, y, variant='b')
    return float(res.statistic)


def brier(prob: Sequence[float], labels: Sequence[int]) -> float:
    """Brier score (mean squared error of probabilities)."""
    p = np.asarray(prob)
    y = np.asarray(labels)
    return float(np.mean((p - y) ** 2))


def calibration_bins(prob: Sequence[float], labels: Sequence[int], n_bins: int = 10) -> list[tuple[float, float, int]]:
    """Calibration bins.

    Returns a list of (mean_predicted, fraction_positive, count) skipping empty bins.
    """
    p = np.asarray(prob)
    y = np.asarray(labels)
    bins = np.linspace(0, 1, n_bins + 1)

    # We want bins to include the right edge. np.digitize bins: bins[i-1] <= x < bins[i]
    # For the last bin, we want it to include 1.0.
    indices = np.digitize(p, bins, right=False)
    # digitize returns 1 for [0, 0.1), ... 10 for [0.9, 1.0), and 11 for exactly 1.0.
    # We map 11 to 10 so 1.0 is in the last bin.
    indices[indices == n_bins + 1] = n_bins

    result = []
    for i in range(1, n_bins + 1):
        mask = indices == i
        count = int(np.sum(mask))
        if count > 0:
            mean_pred = float(np.mean(p[mask]))
            frac_pos = float(np.mean(y[mask] == 1))
            result.append((mean_pred, frac_pos, count))
    return result


@dataclass
class BootstrapResult:
    estimate: float
    low: float
    high: float
    n_boot_used: int
    n_skipped: int


def bootstrap_ci(metric: Callable, *arrays: Sequence[Any], n_boot: int = 2000, alpha: float = 0.05,
                 clusters: Optional[Sequence[Any]] = None, rng: Optional[int | np.random.Generator] = None) -> BootstrapResult:
    """Percentile bootstrap confidence interval."""
    rng = np.random.default_rng(rng)

    arrays = [np.asarray(a) for a in arrays]
    n = len(arrays[0])
    for a in arrays:
        if len(a) != n:
            raise ValueError("All arrays must have the same length.")

    estimate = metric(*arrays)

    boot_vals = []
    n_skipped = 0

    if clusters is not None:
        clusters = np.asarray(clusters)
        unique_clusters = np.unique(clusters)
        n_clusters = len(unique_clusters)

        cluster_indices = [np.where(clusters == c)[0] for c in unique_clusters]
        resampled_clusters_matrix = rng.integers(0, n_clusters, size=(n_boot, n_clusters))

        for i in range(n_boot):
            idx = np.concatenate([cluster_indices[c] for c in resampled_clusters_matrix[i]])

            resampled_arrays = [a[idx] for a in arrays]
            try:
                val = metric(*resampled_arrays)
                boot_vals.append(val)
            except ValueError:
                n_skipped += 1
    else:
        idx_matrix = rng.integers(0, n, size=(n_boot, n))
        for i in range(n_boot):
            idx = idx_matrix[i]
            resampled_arrays = [a[idx] for a in arrays]
            try:
                val = metric(*resampled_arrays)
                boot_vals.append(val)
            except ValueError:
                n_skipped += 1

    if not boot_vals:
        raise ValueError("All bootstrap samples skipped.")

    low = float(np.percentile(boot_vals, 100 * alpha / 2))
    high = float(np.percentile(boot_vals, 100 * (1 - alpha / 2)))

    return BootstrapResult(estimate=estimate, low=low, high=high, n_boot_used=len(boot_vals), n_skipped=n_skipped)


def paired_difference_ci(metric: Callable, scores_a: Sequence[float], scores_b: Sequence[float], labels: Sequence[int],
                         n_boot: int = 2000, alpha: float = 0.05, clusters: Optional[Sequence[Any]] = None,
                         rng: Optional[int | np.random.Generator] = None) -> BootstrapResult:
    """Bootstrap confidence interval for metric(scores_a, labels) - metric(scores_b, labels) on the same resamples."""
    rng = np.random.default_rng(rng)

    scores_a = np.asarray(scores_a)
    scores_b = np.asarray(scores_b)
    labels = np.asarray(labels)
    n = len(labels)

    estimate = metric(scores_a, labels) - metric(scores_b, labels)

    boot_vals = []
    n_skipped = 0

    if clusters is not None:
        clusters = np.asarray(clusters)
        unique_clusters = np.unique(clusters)
        n_clusters = len(unique_clusters)

        cluster_indices = [np.where(clusters == c)[0] for c in unique_clusters]
        resampled_clusters_matrix = rng.integers(0, n_clusters, size=(n_boot, n_clusters))

        for i in range(n_boot):
            idx = np.concatenate([cluster_indices[c] for c in resampled_clusters_matrix[i]])

            resampled_a = scores_a[idx]
            resampled_b = scores_b[idx]
            resampled_labels = labels[idx]

            try:
                val_a = metric(resampled_a, resampled_labels)
                val_b = metric(resampled_b, resampled_labels)
                boot_vals.append(val_a - val_b)
            except ValueError:
                n_skipped += 1
    else:
        idx_matrix = rng.integers(0, n, size=(n_boot, n))
        for i in range(n_boot):
            idx = idx_matrix[i]
            resampled_a = scores_a[idx]
            resampled_b = scores_b[idx]
            resampled_labels = labels[idx]

            try:
                val_a = metric(resampled_a, resampled_labels)
                val_b = metric(resampled_b, resampled_labels)
                boot_vals.append(val_a - val_b)
            except ValueError:
                n_skipped += 1

    if not boot_vals:
        raise ValueError("All bootstrap samples skipped.")

    low = float(np.percentile(boot_vals, 100 * alpha / 2))
    high = float(np.percentile(boot_vals, 100 * (1 - alpha / 2)))

    return BootstrapResult(estimate=estimate, low=low, high=high, n_boot_used=len(boot_vals), n_skipped=n_skipped)

"""Survival analysis tools for evaluating healthy lifespan hypotheses.

This module provides an implementation of the k-sample log-rank test for right-censored
survival data, including standard variance computation with support for ties, stratified
log-rank testing, and permutation null distribution generation.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

import numpy as np
import scipy.stats


class LogRankResult(NamedTuple):
    """Result of a k-sample log-rank test."""
    chi2: float
    p_value: float
    n_groups: int
    df: int


def _compute_uv(times: np.ndarray, events: np.ndarray, groups: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Compute the U statistic vector and V variance matrix for the log-rank test."""
    order = np.argsort(times)
    t = times[order]
    e = events[order]
    g = groups[order]

    U = np.zeros(k, dtype=float)
    V = np.zeros((k, k), dtype=float)

    n_samples = len(t)
    risk_counts = np.bincount(g, minlength=k).astype(int)

    i = 0
    while i < n_samples:
        current_time = t[i]

        events_at_t = np.zeros(k, dtype=int)
        j = i
        while j < n_samples and t[j] == current_time:
            if e[j] == 1:
                events_at_t[g[j]] += 1
            j += 1

        N_ij = risk_counts
        N_j = np.sum(N_ij)
        O_ij = events_at_t
        O_j = np.sum(O_ij)

        if O_j > 0 and N_j > 1:
            E_ij = O_j * (N_ij / N_j)
            U += (O_ij - E_ij)

            var_factor = (O_j * (N_j - O_j)) / (N_j**2 * (N_j - 1))
            diag_N = np.diag(N_ij) * N_j
            outer_N = np.outer(N_ij, N_ij)
            V += var_factor * (diag_N - outer_N)

        for idx in range(i, j):
            risk_counts[g[idx]] -= 1

        i = j

    return U, V


def logrank_test(times: np.ndarray | list, events: np.ndarray | list, groups: np.ndarray | list) -> LogRankResult:
    """Perform a k-sample log-rank test with right censoring and ties.

    Args:
        times: Array of observed times.
        events: Array of event indicators (1 = event, 0 = censored).
        groups: Array of group indices (integers from 0 to k-1).

    Returns:
        LogRankResult containing chi2 statistic, p-value, number of groups, and degrees of freedom.
    """
    times = np.asarray(times)
    events = np.asarray(events)
    groups = np.asarray(groups, dtype=int)

    if len(times) == 0:
        raise ValueError("Inputs cannot be empty.")

    unique_groups = np.unique(groups)
    k = np.max(unique_groups) + 1

    if k < 2:
        raise ValueError("Require at least two groups.")

    counts = np.bincount(groups)
    if len(counts) != k or np.any(counts == 0):
        raise ValueError("One or more groups are empty (Groups must be zero-indexed contiguous integers).")


    U, V = _compute_uv(times, events, groups, k)

    # Calculate chi-squared statistic
    try:
        chi2 = U @ np.linalg.pinv(V) @ U
    except np.linalg.LinAlgError:
        chi2 = 0.0

    df = k - 1
    p_value = scipy.stats.chi2.sf(chi2, df) if df > 0 else 1.0

    return LogRankResult(chi2=float(chi2), p_value=float(p_value), n_groups=k, df=df)


def permutation_null(times: np.ndarray | list, events: np.ndarray | list, groups: np.ndarray | list,
                     strata: Optional[np.ndarray | list] = None, n_perm: int = 1000,
                     rng: Optional[np.random.Generator | int] = None) -> np.ndarray:
    """Generate the permutation null distribution of the log-rank chi2 statistic.

    Args:
        times: Array of observed times.
        events: Array of event indicators (1 = event, 0 = censored).
        groups: Array of group indices.
        strata: Array of stratum indices. If None, assumes a single stratum.
        n_perm: Number of permutations to run.
        rng: Random number generator or seed.

    Returns:
        Array of chi2 statistics under the permutation null.
    """
    times = np.asarray(times)
    events = np.asarray(events)
    groups = np.asarray(groups, dtype=int)

    if strata is None:
        strata = np.zeros(len(times), dtype=int)
    else:
        strata = np.asarray(strata)

    if not isinstance(rng, np.random.Generator):
        rng = np.random.default_rng(rng)

    k = np.max(groups) + 1
    chi2_null = np.zeros(n_perm, dtype=float)

    unique_strata = np.unique(strata)

    # Pre-calculate sorting for efficient group assignment
    indices_by_stratum = {s: np.where(strata == s)[0] for s in unique_strata}

    for p in range(n_perm):
        permuted_groups = np.empty_like(groups)
        for s, idxs in indices_by_stratum.items():
            permuted_groups[idxs] = rng.permutation(groups[idxs])

        # Stratified logrank for this permutation
        U_total = np.zeros(k, dtype=float)
        V_total = np.zeros((k, k), dtype=float)

        for s, idxs in indices_by_stratum.items():
            U, V = _compute_uv(times[idxs], events[idxs], permuted_groups[idxs], k)
            U_total += U
            V_total += V

        try:
            chi2 = U_total @ np.linalg.pinv(V_total) @ U_total
        except np.linalg.LinAlgError:
            chi2 = 0.0

        chi2_null[p] = chi2

    return chi2_null


def stratified_logrank(times: np.ndarray | list, events: np.ndarray | list,
                       groups: np.ndarray | list, strata: np.ndarray | list) -> LogRankResult:
    """Perform a stratified k-sample log-rank test.

    Args:
        times: Array of observed times.
        events: Array of event indicators (1 = event, 0 = censored).
        groups: Array of group indices.
        strata: Array of stratum indices.

    Returns:
        LogRankResult containing combined chi2 statistic and p-value.
    """
    times = np.asarray(times)
    events = np.asarray(events)
    groups = np.asarray(groups, dtype=int)
    strata = np.asarray(strata)

    unique_groups = np.unique(groups)
    k = np.max(unique_groups) + 1

    unique_strata = np.unique(strata)

    U_total = np.zeros(k, dtype=float)
    V_total = np.zeros((k, k), dtype=float)

    for s in unique_strata:
        mask = (strata == s)
        t_s = times[mask]
        e_s = events[mask]
        g_s = groups[mask]

        if len(t_s) == 0:
            continue

        U, V = _compute_uv(t_s, e_s, g_s, k)
        U_total += U
        V_total += V

    try:
        chi2 = U_total @ np.linalg.pinv(V_total) @ U_total
    except np.linalg.LinAlgError:
        chi2 = 0.0

    df = k - 1
    p_value = scipy.stats.chi2.sf(chi2, df) if df > 0 else 1.0

    return LogRankResult(chi2=float(chi2), p_value=float(p_value), n_groups=k, df=df)

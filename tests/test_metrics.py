import numpy as np
import pytest
import scipy.stats

from hyparena.tools.metrics import auc, precision_at_k, spearman, kendall_tau, brier, calibration_bins, bootstrap_ci, paired_difference_ci

def test_auc_perfect_reversed_tied():
    assert auc([0.1, 0.4, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert auc([0.9, 0.8, 0.4, 0.1], [0, 0, 1, 1]) == 0.0
    assert auc([0.5, 0.5, 0.5, 0.5], [0, 0, 1, 1]) == 0.5

def test_auc_mann_whitney():
    rng = np.random.default_rng(42)
    scores = rng.integers(0, 10, size=100) # lots of ties
    labels = rng.integers(0, 2, size=100)

    pos_scores = scores[labels == 1]
    neg_scores = scores[labels == 0]
    u = scipy.stats.mannwhitneyu(pos_scores, neg_scores, alternative='two-sided').statistic
    expected = u / (len(pos_scores) * len(neg_scores))

    assert np.isclose(auc(scores, labels), expected)

def test_auc_single_class():
    with pytest.raises(ValueError, match="AUC requires both positive and negative classes"):
        auc([1.0, 2.0, 3.0], [1, 1, 1])

def test_precision_at_k():
    scores = [0.9, 0.8, 0.8, 0.8, 0.7, 0.6]
    labels = [1,   0,   1,   0,   1,   0]

    # top 1: 0.9 (1) -> 1.0
    assert precision_at_k(scores, labels, 1) == 1.0

    # top 2: 0.9 (1), 0.8 (0, first 0.8) -> 0.5
    assert precision_at_k(scores, labels, 2) == 0.5

    # top 3: 0.9 (1), 0.8 (0), 0.8 (1, second 0.8) -> 2/3
    assert np.isclose(precision_at_k(scores, labels, 3), 2.0/3.0)

    # top 4: 0.9 (1), 0.8 (0), 0.8 (1), 0.8 (0) -> 0.5
    assert precision_at_k(scores, labels, 4) == 0.5

def test_brier_and_calibration():
    prob = [0.1, 0.2, 0.2, 0.8, 0.9]
    labels = [0, 0, 1, 1, 1]

    # brier = mean( (0.1)^2 + (0.2)^2 + (0.8)^2 + (-0.2)^2 + (-0.1)^2 )
    # = (0.01 + 0.04 + 0.64 + 0.04 + 0.01) / 5 = 0.74 / 5 = 0.148
    assert np.isclose(brier(prob, labels), 0.148)

    bins = calibration_bins(prob, labels, n_bins=5)
    # bins: [0, 0.2), [0.2, 0.4), [0.4, 0.6), [0.6, 0.8), [0.8, 1.0]
    # 0.1 is in bin 1. Mean pred = 0.1, frac_pos = 0, count = 1
    # 0.2, 0.2 are in bin 2. Mean pred = 0.2, frac_pos = 0.5, count = 2
    # 0.8, 0.9 are in bin 5. Mean pred = 0.85, frac_pos = 1.0, count = 2
    assert len(bins) == 3
    assert np.allclose(bins[0], (0.1, 0.0, 1))
    assert np.allclose(bins[1], (0.2, 0.5, 2))
    assert np.allclose(bins[2], (0.85, 1.0, 2))

def test_bootstrap_coverage():
    # simulate datasets from binormal model
    # pos ~ N(d, 1), neg ~ N(0, 1)
    # AUC = Phi(d / sqrt(2)). For true AUC = 0.75, d = sqrt(2) * Phi^{-1}(0.75)
    # Phi^{-1}(0.75) ~ 0.67448975, d ~ 0.95387
    true_auc = 0.75
    d = np.sqrt(2) * scipy.stats.norm.ppf(true_auc)

    rng = np.random.default_rng(42)
    n_sims = 300
    n_items = 60

    hits = 0

    for _ in range(n_sims):
        labels = rng.choice([0, 1], size=n_items)
        scores = rng.normal(loc=labels * d, scale=1.0)

        # fast bootstrap for testing
        res = bootstrap_ci(auc, scores, labels, n_boot=200, alpha=0.05, rng=rng)
        if res.low <= true_auc <= res.high:
            hits += 1

    coverage = hits / n_sims
    assert 0.90 <= coverage <= 0.99, f"Coverage out of bounds: {coverage}"

def test_bootstrap_cluster():
    rng = np.random.default_rng(42)

    # 10 clusters, 10 items each
    clusters = np.repeat(np.arange(10), 10)
    # within cluster, labels are identical
    cluster_labels = rng.choice([0, 1], size=10)
    labels = np.repeat(cluster_labels, 10)

    # scores are very similar within cluster
    cluster_scores = rng.normal(loc=cluster_labels * 1.0, scale=1.0)
    scores = np.repeat(cluster_scores, 10) + rng.normal(scale=0.1, size=100)

    # If we bootstrap items (naive), we think we have 100 independent samples, interval will be narrow.
    # If we bootstrap clusters, we know we only have 10 independent samples, interval will be wider.
    res_naive = bootstrap_ci(auc, scores, labels, n_boot=200, rng=rng)
    res_cluster = bootstrap_ci(auc, scores, labels, n_boot=200, clusters=clusters, rng=rng)

    naive_width = res_naive.high - res_naive.low
    cluster_width = res_cluster.high - res_cluster.low

    assert cluster_width > naive_width

def test_paired_difference_ci():
    rng = np.random.default_rng(42)
    labels = rng.choice([0, 1], size=100)
    scores = rng.normal(loc=labels, scale=1.0)

    # Same scores for a and b
    res = paired_difference_ci(auc, scores, scores, labels, n_boot=200, rng=rng)

    assert res.estimate == 0.0
    assert res.low <= 0.0 <= res.high
    # Very narrow
    assert res.high - res.low < 1e-9

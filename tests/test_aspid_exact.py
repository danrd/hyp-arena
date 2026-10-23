"""Exact reference tests for ASPID aggregation on small problems, and tie-rule tests."""
import math

import numpy as np
import pytest

from hyparena.aspid import IndicatorSpec, Profile, aggregate
from hyparena.snapshot import places

def _exact_simplex_reference(Q: np.ndarray, mode: str, k_top: int = 2) -> dict:
    """Numerically calculate exact expected values and probabilities over a fine grid of weights."""
    N = 2500
    w1_1d = np.linspace(0, 1, N)
    w2_1d = np.linspace(0, 1, N)
    w1, w2 = np.meshgrid(w1_1d, w2_1d)

    if mode == "uniform":
        mask = w1 + w2 <= 1.0
        w1, w2 = w1[mask], w2[mask]
        w3 = 1.0 - w1 - w2
        W = np.column_stack([w1, w2, w3])
        expected = Q @ np.array([1/3, 1/3, 1/3])
    elif mode == "tiers":
        mask = (w1 + w2 <= 1.0) & (w1 >= w2) & (w2 >= 1.0 - w1 - w2)
        w1, w2 = w1[mask], w2[mask]
        w3 = 1.0 - w1 - w2
        W = np.column_stack([w1, w2, w3])
        expected = Q @ np.array([11/18, 5/18, 2/18])
    elif mode == "equal_plus_free":
        w1 = np.linspace(0, 0.5, 100000)
        w2 = w1
        w3 = 1.0 - 2 * w1
        W = np.column_stack([w1, w2, w3])
        expected = Q @ np.array([0.25, 0.25, 0.5])
    else:
        raise ValueError(f"Unknown mode {mode}")

    U = W @ Q.T
    np.random.seed(0)
    noise = np.random.random(U.shape) * 1e-12
    ranks = np.argsort(-(U + noise), axis=1).argsort(axis=1)

    p_best = (ranks == 0).mean(axis=0)
    p_topk = (ranks < k_top).mean(axis=0)
    return {"expected": expected, "p_best": p_best, "p_topk": p_topk}


def _check_against_exact(Q: np.ndarray, mode: str, profile: Profile, K: int = 20000, seed: int = 42) -> list[str]:
    """Helper to run aggregate and compare against the exact reference."""
    indicators = [
        IndicatorSpec("i1", "cardinal", bounds=(0, 10)),
        IndicatorSpec("i2", "cardinal", bounds=(0, 10)),
        IndicatorSpec("i3", "cardinal", bounds=(0, 10)),
    ]
    values = {f"h{i}": {"i1": Q[i, 0]*10, "i2": Q[i, 1]*10, "i3": Q[i, 2]*10} for i in range(len(Q))}

    res = aggregate(values, indicators, profile, K=K, seed=seed, k_top=2)
    ref = _exact_simplex_reference(Q, mode, k_top=2)

    mismatches = []
    for h in res.ids:
        i = int(h.replace('h', ''))
        mc_se = res.std[h] / math.sqrt(K)
        diff_exp = abs(res.expected[h] - ref["expected"][i])
        if diff_exp > 4 * mc_se:
            mismatches.append(f"{h} expected mismatch: diff={diff_exp:.5f} > 4*SE={4*mc_se:.5f}")

        se_best = math.sqrt(max(ref["p_best"][i] * (1 - ref["p_best"][i]), 0.0) / K)
        diff_best = abs(res.p_best[h] - ref["p_best"][i])
        if diff_best > 4 * se_best + 0.005:  # small tolerance for grid discretisation
            mismatches.append(f"{h} p_best mismatch: diff={diff_best:.5f} > 4*SE={4*se_best:.5f}")

        se_topk = math.sqrt(max(ref["p_topk"][i] * (1 - ref["p_topk"][i]), 0.0) / K)
        diff_topk = abs(res.p_topk[h] - ref["p_topk"][i])
        if diff_topk > 4 * se_topk + 0.005:
            mismatches.append(f"{h} p_topk mismatch: diff={diff_topk:.5f} > 4*SE={4*se_topk:.5f}")

    return mismatches


def test_exact_reference_uniform():
    """Exact reference check for uniform simplex weights (profile=None)."""
    Q = np.array([
        [0.9, 0.5, 0.1],
        [0.7, 0.7, 0.2],
        [0.5, 0.6, 0.8],
        [0.2, 0.8, 0.6],
        [0.3, 0.3, 0.4],
    ])
    mismatches = _check_against_exact(Q, "uniform", None)
    assert not mismatches, "\n".join(mismatches)


def test_exact_reference_tiers():
    """Exact reference check for a profile with strict tiers over all indicators."""
    Q = np.array([
        [0.9, 0.5, 0.1],
        [0.7, 0.7, 0.2],
        [0.5, 0.6, 0.8],
        [0.2, 0.8, 0.6],
        [0.3, 0.3, 0.4],
    ])
    prof = Profile(name="tiers", tiers=[["i1"], ["i2"], ["i3"]])
    mismatches = _check_against_exact(Q, "tiers", prof)
    assert not mismatches, "\n".join(mismatches)


def test_exact_reference_equal_groups():
    """Exact reference check for equal groups and a free indicator."""
    Q = np.array([
        [0.9, 0.5, 0.1],
        [0.7, 0.7, 0.2],
        [0.5, 0.6, 0.8],
        [0.2, 0.8, 0.6],
        [0.3, 0.3, 0.4],
    ])
    prof = Profile(name="eq", equal=[["i1", "i2"]])
    mismatches = _check_against_exact(Q, "equal_plus_free", prof)
    assert not mismatches, "\n".join(mismatches)

def test_places_identical_hypotheses():
    """Two hypotheses with identical indicator values share a place range."""
    bundle = {
        "expected": {"h1": 0.5, "h2": 0.5},
        "std": {"h1": 0.1, "h2": 0.1},
        "K": 10000,
        "order": ["h1", "h2"]
    }
    p = places(bundle)
    assert p == {"h1": "1-2", "h2": "1-2"}


def test_places_dominating():
    """A hypothesis that dominates every indicator never shares a range with a dominated one at K=10000."""
    # Worst case std for [0, 1] bounded values is 0.5 (var = 0.25).
    # Expected difference between 1.0 (dominant) and 0.0 (dominated) is 1.0.
    # At K=10000, max bound is 1.96 * sqrt((0.5^2 + 0.5^2) / 10000) = 1.96 * sqrt(0.5 / 10000) ≈ 0.0138
    # 1.0 > 0.0138, so they should never tie.
    bundle = {
        "expected": {"dom": 1.0, "sub": 0.0},
        "std": {"dom": 0.5, "sub": 0.5},
        "K": 10000,
        "order": ["dom", "sub"]
    }
    p = places(bundle)
    assert p == {"dom": "1", "sub": "2"}


def test_places_seed_independence():
    """The grouping computed from aggregate() results does not depend on the seed for clear gaps,
    and groups are consecutive in the order."""
    indicators = [
        IndicatorSpec("i1", "cardinal", bounds=(0, 10)),
        IndicatorSpec("i2", "cardinal", bounds=(0, 10))
    ]
    # Pairs of identical values with a clear gap between pairs
    values = {
        "h1": {"i1": 9, "i2": 9},
        "h2": {"i1": 9, "i2": 9},
        "h3": {"i1": 2, "i2": 2},
        "h4": {"i1": 2, "i2": 2},
    }

    first_places = None
    for seed in range(5):
        res = aggregate(values, indicators, None, K=10000, seed=seed, k_top=2)
        bundle = {
            "expected": res.expected,
            "std": res.std,
            "K": res.meta["K"],
            "order": res.order
        }
        p = places(bundle)
        if first_places is None:
            first_places = p
        else:
            assert p == first_places, f"Places mismatched at seed {seed}"

    # Also verify the places are consecutive as expected
    assert set(first_places.values()) == {"1-2", "3-4"}

def test_mismatch_helper_reports_failure():
    """A test that fails when it should: break the reference on purpose and assert mismatches."""
    Q = np.array([
        [0.9, 0.5, 0.1],
        [0.7, 0.7, 0.2],
        [0.5, 0.6, 0.8],
        [0.2, 0.8, 0.6],
        [0.3, 0.3, 0.4],
    ])
    # Pass 'tiers' exact mode but evaluate it with uniform weights (profile=None)
    mismatches = _check_against_exact(Q, mode="tiers", profile=None, K=20000)
    assert mismatches, "Comparison helper should have reported a mismatch but it didn't."
    assert any("expected mismatch" in m for m in mismatches), "Should report an expected mismatch"

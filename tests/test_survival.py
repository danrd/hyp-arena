import numpy as np
import pytest
import scipy.stats
import scipy.stats.distributions as dist
from scipy.stats import CensoredData

from hyparena.tools.survival import logrank_test, permutation_null, stratified_logrank, _compute_uv

def test_logrank_hand_checked():
    # Hand-checked example:
    # times = [5, 5, 10, 12, 15, 20]
    # events = [1, 0, 1, 1, 0, 1]
    # groups = [0, 1, 0, 1, 0, 1]
    #
    # At t=5: N0=3, N1=3, N=6. e0=1, e1=0, O=1. E0 = 1*(3/6) = 0.5. U0 += 0.5, U1 += -0.5
    # Variance factor = 1*5/(36*5) = 1/36.
    # V00 = 1/36 * (3*6 - 9) = 1/4. V01 = -1/4
    #
    # At t=10: N0=2, N1=2, N=4. e0=1, e1=0, O=1. E0 = 1*(2/4) = 0.5. U0 += 0.5, U1 += -0.5
    # Variance factor = 1*3/(16*3) = 1/16.
    # V00 = 1/16 * (2*4 - 4) = 1/4. V01 = -1/4
    #
    # At t=12: N0=1, N1=2, N=3. e0=0, e1=1, O=1. E0 = 1*(1/3) = 1/3. U0 += -1/3, U1 += 1/3
    # Variance factor = 1*2/(9*2) = 1/9.
    # V00 = 1/9 * (1*3 - 1) = 2/9. V01 = -2/9
    #
    # At t=20: N0=0, N1=1, N=1. O=1. (N>1 is false, so no contribution)
    #
    # Total U0 = 0.5 + 0.5 - 1/3 = 2/3.
    # Total V00 = 1/4 + 1/4 + 2/9 = 13/18.
    # chi2 = (2/3)^2 / (13/18) = (4/9) * (18/13) = 8/13 = 0.6153846...
    times = [5, 5, 10, 12, 15, 20]
    events = [1, 0, 1, 1, 0, 1]
    groups = [0, 1, 0, 1, 0, 1]

    res = logrank_test(times, events, groups)
    assert np.isclose(res.chi2, 0.6153846153846156)
    assert res.n_groups == 2
    assert res.df == 1

def test_cross_check_scipy():
    if not hasattr(scipy.stats, "CensoredData"):
        pytest.skip("scipy.stats.CensoredData not available")

    times = np.array([5, 5, 10, 12, 15, 20, 22, 25, 30, 35])
    events = np.array([1, 0, 1, 1, 0, 1, 1, 0, 1, 0])
    groups = np.array([0, 1, 0, 1, 0, 1, 0, 1, 0, 1])

    res = logrank_test(times, events, groups)

    cd0 = CensoredData(uncensored=times[(groups == 0) & (events == 1)], right=times[(groups == 0) & (events == 0)])
    cd1 = CensoredData(uncensored=times[(groups == 1) & (events == 1)], right=times[(groups == 1) & (events == 0)])
    scipy_res = scipy.stats.logrank(x=cd0, y=cd1)

    assert np.isclose(res.chi2, scipy_res.statistic**2, atol=1e-6)
    assert np.isclose(res.p_value, scipy_res.pvalue, atol=1e-6)

def test_edge_cases():
    with pytest.raises(ValueError, match="Groups must be zero-indexed"):
        logrank_test([10, 10, 20], [1, 1, 1], [0, 2, 0])

    with pytest.raises(ValueError, match="at least two groups"):
        logrank_test([10, 20], [1, 1], [0, 0])

    with pytest.raises(ValueError, match="empty"):
        logrank_test([], [], [])

    # test one group empty
    with pytest.raises(ValueError, match="One or more groups are empty"):
        logrank_test([10, 20, 30], [1, 1, 1], [0, 1, 3]) # max group is 3, groups 2 is empty

def test_stratified_equals_unstratified():
    times = np.array([5, 5, 10, 12, 15, 20])
    events = np.array([1, 0, 1, 1, 0, 1])
    groups = np.array([0, 1, 0, 1, 0, 1])
    strata = np.array([0, 0, 0, 0, 0, 0])

    res_stratified = stratified_logrank(times, events, groups, strata)
    res_unstratified = logrank_test(times, events, groups)

    assert np.isclose(res_stratified.chi2, res_unstratified.chi2)
    assert np.isclose(res_stratified.p_value, res_unstratified.p_value)

def simulate_dataset(n_per_group: int, hr: float, censor_rate: float, rng: np.random.Generator):
    times_0 = rng.exponential(scale=1.0, size=n_per_group)
    times_1 = rng.exponential(scale=1.0 / hr, size=n_per_group)

    times = np.concatenate([times_0, times_1])
    groups = np.concatenate([np.zeros(n_per_group), np.ones(n_per_group)])

    # Truly random censoring: Exponentially distributed censoring times for each subject
    # P(T > C) = lambda_c / (lambda + lambda_c). We want average censor rate to be ~30%
    # Mean hazard is approx (1+hr)/2. lambda_c = 0.3 * lambda_mean / 0.7
    censor_mask = rng.random(len(times)) < censor_rate
    C = np.where(censor_mask, rng.uniform(0, times), np.inf)

    observed_times = np.minimum(times, C)
    events = (times <= C).astype(int)

    return observed_times, events, groups

def test_null_calibration():
    rng = np.random.default_rng(42)
    alpha = 0.05
    n_sims = 500
    n_per_group = 40
    censor_rate = 0.3

    rejections = 0
    for _ in range(n_sims):
        t, e, g = simulate_dataset(n_per_group, hr=1.0, censor_rate=censor_rate, rng=rng)
        res = logrank_test(t, e, g)
        if res.p_value < alpha:
            rejections += 1

    false_find_rate = rejections / n_sims
    lower, upper = dist.binom.interval(0.99, n_sims, alpha)
    assert lower <= rejections <= upper, f"False find rate {false_find_rate} outside 99% interval [{lower/n_sims}, {upper/n_sims}]"

def test_power():
    rng = np.random.default_rng(25)
    alpha = 0.05
    n_sims = 500
    n_per_group = 40
    censor_rate = 0.3

    hrs = [1.0, 1.3, 1.6, 2.0]
    rejection_rates = []

    for hr in hrs:
        rejections = 0
        for _ in range(n_sims):
            t, e, g = simulate_dataset(n_per_group, hr=hr, censor_rate=censor_rate, rng=rng)
            res = logrank_test(t, e, g)
            if res.p_value < alpha:
                rejections += 1
        rejection_rates.append(rejections / n_sims)

    for i in range(1, len(rejection_rates)):
        assert rejection_rates[i] >= rejection_rates[i-1]

    assert rejection_rates[-1] > 0.8

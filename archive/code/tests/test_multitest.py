import numpy as np
import pytest

from hyparena.tools.multitest import (
    bonferroni,
    holm,
    benjamini_hochberg,
    benjamini_yekutieli,
    p_to_e,
    e_bh,
    combine_e_values
)


def test_hand_computed_examples():
    p = np.array([0.01, 0.04, 0.03, 0.005])
    alpha = 0.05
    m = len(p)

    # Bonferroni
    # adjusted p = min(1, p * 4)
    # [0.01*4, 0.04*4, 0.03*4, 0.005*4] = [0.04, 0.16, 0.12, 0.02]
    res_bonf = bonferroni(p, alpha)
    np.testing.assert_allclose(res_bonf.adjusted_p, [0.04, 0.16, 0.12, 0.02])
    np.testing.assert_array_equal(res_bonf.reject, [True, False, False, True])

    # Holm
    # Ordered p: p[3]=0.005, p[0]=0.01, p[2]=0.03, p[1]=0.04
    # Multipliers: 4, 3, 2, 1
    # p * multipliers = [0.02, 0.03, 0.06, 0.04]
    # Adjusted ordered: max.accumulate = [0.02, 0.03, 0.06, 0.06]
    # Re-order: [0.03, 0.06, 0.06, 0.02]
    res_holm = holm(p, alpha)
    np.testing.assert_allclose(res_holm.adjusted_p, [0.03, 0.06, 0.06, 0.02])
    np.testing.assert_array_equal(res_holm.reject, [True, False, False, True])

    # Benjamini-Hochberg (BH)
    # Ordered p: p[3]=0.005, p[0]=0.01, p[2]=0.03, p[1]=0.04
    # Multipliers m/i: 4/1, 4/2, 4/3, 4/4
    # p * multipliers = [0.02, 0.02, 0.04, 0.04]
    # Adjusted ordered: min.accumulate from right = [0.02, 0.02, 0.04, 0.04]
    # Re-order: [0.02, 0.04, 0.04, 0.02]
    res_bh = benjamini_hochberg(p, alpha)
    np.testing.assert_allclose(res_bh.adjusted_p, [0.02, 0.04, 0.04, 0.02])
    np.testing.assert_array_equal(res_bh.reject, [True, True, True, True])

    # Benjamini-Yekutieli (BY)
    # c_m = 1/1 + 1/2 + 1/3 + 1/4 = 25/12 approx 2.08333
    # Multipliers m * c_m / i = 4 * 2.08333 / i = 8.333 / i
    # Ordered p: 0.005, 0.01, 0.03, 0.04
    # p * mult = [0.041666, 0.041666, 0.083333, 0.083333]
    # Adjusted ordered: min.accumulate from right = [0.041666, 0.041666, 0.083333, 0.083333]
    # Re-order: [0.041666, 0.083333, 0.083333, 0.041666]
    res_by = benjamini_yekutieli(p, alpha)
    np.testing.assert_allclose(res_by.adjusted_p, [0.04166667, 0.08333333, 0.08333333, 0.04166667])
    np.testing.assert_array_equal(res_by.reject, [True, False, False, True])


def test_relationships():
    np.random.seed(42)
    p = np.random.uniform(0, 1, 50)
    alpha = 0.05

    rej_bonf = bonferroni(p, alpha).reject
    rej_holm = holm(p, alpha).reject
    rej_bh = benjamini_hochberg(p, alpha).reject

    # Holm rejects at least what Bonferroni rejects
    assert np.all(rej_holm[rej_bonf])

    # BH rejects at least what Holm rejects
    assert np.all(rej_bh[rej_holm])

    # Adjusted p-values are monotone with respect to original p-values
    p_order = np.argsort(p)

    adj_bonf = bonferroni(p, alpha).adjusted_p
    assert np.all(np.diff(adj_bonf[p_order]) >= 0)
    assert np.all((adj_bonf >= 0) & (adj_bonf <= 1))

    adj_holm = holm(p, alpha).adjusted_p
    assert np.all(np.diff(adj_holm[p_order]) >= 0)
    assert np.all((adj_holm >= 0) & (adj_holm <= 1))

    adj_bh = benjamini_hochberg(p, alpha).adjusted_p
    assert np.all(np.diff(adj_bh[p_order]) >= -1e-9) # Allow small float issues
    assert np.all((adj_bh >= 0) & (adj_bh <= 1))

    adj_by = benjamini_yekutieli(p, alpha).adjusted_p
    assert np.all(np.diff(adj_by[p_order]) >= -1e-9)
    assert np.all((adj_by >= 0) & (adj_by <= 1))


def test_e_values():
    p = np.array([0.01, 0.1, 0.5])
    # p_to_e with kappa=0.5 -> 0.5 * p**(-0.5)
    # 0.01 -> 0.5 * 10 = 5.0
    # 0.1 -> 0.5 * 3.162 = 1.581
    # 0.5 -> 0.5 * 1.414 = 0.707
    e = p_to_e(p, kappa=0.5)
    np.testing.assert_allclose(e, [5.0, 1.5811388, 0.70710678])

    # e-BH hand computed
    # m = 3, alpha = 0.05
    # e ordered: 5.0, 1.581, 0.707
    # thresholds m / (alpha * k) = 3 / (0.05 * k) = 60 / k
    # k=1: 60/1 = 60.  5.0 >= 60 (False)
    # k=2: 60/2 = 30.  1.581 >= 30 (False)
    # k=3: 60/3 = 20.  0.707 >= 20 (False)
    # No rejections
    rej = e_bh(e, alpha=0.05)
    np.testing.assert_array_equal(rej, [False, False, False])

    # Let's try with larger e-values to get a rejection
    e2 = np.array([100.0, 50.0, 1.0])
    # m = 3, alpha = 0.5 (to make it easy)
    # thresholds m / (alpha * k) = 3 / (0.5 * k) = 6 / k
    # k=1: 6. 100 >= 6 (True)
    # k=2: 3. 50 >= 3 (True)
    # k=3: 2. 1 >= 2 (False)
    # k_star = 2. So reject top 2.
    rej2 = e_bh(e2, alpha=0.5)
    np.testing.assert_array_equal(rej2, [True, True, False])

    # combine_e_values
    e_list = [np.array([2.0, 3.0]), np.array([4.0, 0.5])]
    combined = combine_e_values(e_list)
    np.testing.assert_array_equal(combined, [8.0, 1.5])


def test_validation():
    with pytest.raises(ValueError):
        bonferroni([-0.1, 0.5])
    with pytest.raises(ValueError):
        holm([0.5, 1.1])
    with pytest.raises(ValueError):
        benjamini_hochberg([0.5, np.nan])
    with pytest.raises(ValueError):
        p_to_e([0.5], kappa=1.5)
    with pytest.raises(ValueError):
        e_bh([-1.0, 5.0])

    # empty arrays
    res_empty = bonferroni([])
    assert len(res_empty.reject) == 0
    assert len(res_empty.adjusted_p) == 0

    assert len(e_bh([])) == 0


def test_simulation():
    np.random.seed(42)
    m = 200
    n_null = int(m * 0.8)
    n_alt = m - n_null
    alpha = 0.05
    n_rep = 2000

    fdp_bh = []
    fdp_ebh = []
    fwer_holm = []
    fwer_bonf = []

    for _ in range(n_rep):
        p_null = np.random.uniform(0, 1, n_null)
        p_alt = np.random.beta(0.5, 10, n_alt) # beta with small first param
        p = np.concatenate([p_null, p_alt])

        # False Discovery Proportion for BH
        rej_bh = benjamini_hochberg(p, alpha).reject
        n_rej_bh = np.sum(rej_bh)
        v_bh = np.sum(rej_bh[:n_null])
        fdp_bh.append(v_bh / n_rej_bh if n_rej_bh > 0 else 0.0)

        # False Discovery Proportion for e-BH
        e = p_to_e(p, kappa=0.5)
        rej_ebh = e_bh(e, alpha)
        n_rej_ebh = np.sum(rej_ebh)
        v_ebh = np.sum(rej_ebh[:n_null])
        fdp_ebh.append(v_ebh / n_rej_ebh if n_rej_ebh > 0 else 0.0)

        # Family-wise Error Rate for Holm and Bonferroni (all nulls)
        p_all_null = np.random.uniform(0, 1, m)
        rej_holm_null = holm(p_all_null, alpha).reject
        fwer_holm.append(np.any(rej_holm_null))

        rej_bonf_null = bonferroni(p_all_null, alpha).reject
        fwer_bonf.append(np.any(rej_bonf_null))

    mean_fdp_bh = np.mean(fdp_bh)
    mean_fdp_ebh = np.mean(fdp_ebh)
    fwer_h = np.mean(fwer_holm)
    fwer_b = np.mean(fwer_bonf)

    assert mean_fdp_bh <= alpha + 0.01
    assert mean_fdp_ebh <= alpha + 0.01
    assert fwer_h <= alpha + 0.01
    assert fwer_b <= alpha + 0.01

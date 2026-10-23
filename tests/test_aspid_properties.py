import math
import numpy as np
from scipy.stats import spearmanr
from dataclasses import replace
from hyparena.aspid import IndicatorSpec, aggregate, Profile
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

def test_monotonicity():
    """
    Monotonicity: with a fixed seed, raising the level of one ordinal indicator
    or the value of a cardinal indicator never lowers that hypothesis's expected
    value, p_topk, and p_best. Other hypotheses never gain expected value from it.
    """
    rng = np.random.default_rng(42)
    # create specs where higher is better. effect_size is already cardinal and higher is better.
    specs = [
        IndicatorSpec("ind_ord", "ordinal", levels=("L1", "L2", "L3")),
        IndicatorSpec("ind_card", "cardinal", bounds=(0.0, 10.0))
    ]
    profiles = [None, Profile(name="p1", tiers=[["ind_ord"], ["ind_card"]])]

    for _ in range(3): # several random pools
        pool_base = _generate_random_pool(5, rng, specs)
        h_target = "H0"

        # Test Ordinal increase
        if pool_base[h_target]["ind_ord"] != "L3":
            pool_up_ord = {h: dict(v) for h, v in pool_base.items()}
            pool_up_ord[h_target]["ind_ord"] = "L3" if pool_base[h_target]["ind_ord"] == "L2" else "L2"

            for prof in profiles:
                res_base = aggregate(pool_base, specs, prof, K=1000, seed=123)
                res_up = aggregate(pool_up_ord, specs, prof, K=1000, seed=123)

                assert res_up.expected[h_target] >= res_base.expected[h_target] - 1e-9
                assert res_up.p_topk.get(h_target, 0) >= res_base.p_topk.get(h_target, 0) - 1e-9
                assert res_up.p_best.get(h_target, 0) >= res_base.p_best.get(h_target, 0) - 1e-9

                for h in pool_base:
                    if h != h_target:
                        assert res_up.expected[h] <= res_base.expected[h] + 1e-9

        # Test Cardinal increase
        pool_up_card = {h: dict(v) for h, v in pool_base.items()}
        pool_up_card[h_target]["ind_card"] = min(10.0, pool_base[h_target]["ind_card"] + 1.0)

        for prof in profiles:
            res_base = aggregate(pool_base, specs, prof, K=1000, seed=123)
            res_up = aggregate(pool_up_card, specs, prof, K=1000, seed=123)

            assert res_up.expected[h_target] >= res_base.expected[h_target] - 1e-9
            assert res_up.p_topk.get(h_target, 0) >= res_base.p_topk.get(h_target, 0) - 1e-9
            assert res_up.p_best.get(h_target, 0) >= res_base.p_best.get(h_target, 0) - 1e-9

            for h in pool_base:
                if h != h_target:
                    assert res_up.expected[h] <= res_base.expected[h] + 1e-9


def test_order_of_submission():
    """
    Order of submission: permuting the order of the hypotheses in the input
    gives identical values per hypothesis (same seed).
    """
    rng = np.random.default_rng(10)
    specs = INDICATORS[:3]
    pool = _generate_random_pool(6, rng, specs)

    res1 = aggregate(pool, specs, None, K=1000, seed=99)

    permuted_keys = list(pool.keys())
    rng.shuffle(permuted_keys)
    pool_permuted = {k: pool[k] for k in permuted_keys}

    res2 = aggregate(pool_permuted, specs, None, K=1000, seed=99)

    for h in pool:
        assert np.isclose(res1.expected[h], res2.expected[h], atol=1e-9)
        assert np.isclose(res1.std[h], res2.std[h], atol=1e-9)


def test_seed_stability():
    """
    Seed stability: two seeds at K = 10000 give a rank correlation (Spearman)
    of at least 0.99 between the expected values on a random pool of 20 hypotheses.
    """
    rng = np.random.default_rng(20)
    specs = INDICATORS[:5]
    pool = _generate_random_pool(20, rng, specs)

    res1 = aggregate(pool, specs, None, K=10000, seed=1)
    res2 = aggregate(pool, specs, None, K=10000, seed=2)

    expected1 = [res1.expected[h] for h in pool]
    expected2 = [res2.expected[h] for h in pool]

    corr, _ = spearmanr(expected1, expected2)
    assert corr >= 0.99


def test_duplicate_free_pools():
    """
    Duplicate-free pools: adding a clearly dominated hypothesis does not change
    the expected value of the others (fixed seed) and the dominated one ends last.
    """
    rng = np.random.default_rng(30)
    specs = [
        IndicatorSpec("x", "ordinal", levels=("lo", "mid", "hi")),
        IndicatorSpec("y", "cardinal", bounds=(0, 10))
    ]
    pool = _generate_random_pool(5, rng, specs)

    # Create a clearly dominated hypothesis
    dominated_h = "H_DOM"
    pool_with_dominated = dict(pool)
    pool_with_dominated[dominated_h] = {"x": "lo", "y": 0.0}

    res_base = aggregate(pool, specs, None, K=2000, seed=111)
    res_dom = aggregate(pool_with_dominated, specs, None, K=2000, seed=111)

    for h in pool:
        assert np.isclose(res_base.expected[h], res_dom.expected[h], atol=1e-9)

    assert res_dom.order[-1] == dominated_h


def test_unknown_handling():
    """
    Unknown handling: replacing a known value by None never narrows the 5-95%
    band of that hypothesis.
    """
    rng = np.random.default_rng(40)
    specs = [
        IndicatorSpec("x", "ordinal", levels=("lo", "mid", "hi")),
        IndicatorSpec("y", "cardinal", bounds=(0, 10))
    ]
    pool_base = _generate_random_pool(4, rng, specs)
    h_target = "H0"

    res_base = aggregate(pool_base, specs, None, K=2000, seed=55)
    band_base = res_base.quantiles[h_target][2] - res_base.quantiles[h_target][0]

    pool_unk = {h: dict(v) for h, v in pool_base.items()}
    pool_unk[h_target]["x"] = None

    res_unk = aggregate(pool_unk, specs, None, K=2000, seed=55)
    band_unk = res_unk.quantiles[h_target][2] - res_unk.quantiles[h_target][0]

    assert band_unk >= band_base - 1e-9


def test_sensitivity_script_function():
    """
    Test that the script's compute_sensitivity function runs on a small pool
    and returns tau between -1 and 1.
    """
    import sys
    from pathlib import Path

    # Add scripts to path to import it
    scripts_dir = str(Path(__file__).parent.parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.append(scripts_dir)

    from aspid_sensitivity import compute_sensitivity
    from hyparena.card.indicators import INDICATORS
    from hyparena.aspid import Profile

    rng = np.random.default_rng(123)
    pool = _generate_random_pool(5, rng, INDICATORS)
    prof = Profile("test_prof", tiers=[["effect_size"]])

    tau, ci_low, ci_high = compute_sensitivity(pool, prof, k=1000, seed=42)
    assert -1.0 <= tau <= 1.0
    assert -1.0 <= ci_low <= 1.0
    assert -1.0 <= ci_high <= 1.0

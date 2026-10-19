"""Aggregation tests from Aggregation_Spec section 7."""
import math

import numpy as np
import pytest

from hyparena.aspid import IndicatorSpec, Profile, WeightSampler, aggregate, load_profiles
from hyparena.card.indicators import INDICATORS

IDS = ["a", "b", "c", "d"]


def centroid(n):
    return [sum(1 / k for k in range(j, n + 1)) / n for j in range(1, n + 1)]


def test_uniform_simplex():
    w = WeightSampler(IDS, None).sample(40000, np.random.default_rng(0))
    assert np.allclose(w.mean(0), 0.25, atol=0.01) and np.allclose(w.sum(1), 1)


def test_complete_ranking_gives_centroid_weights():
    prof = Profile(name="rank", tiers=[[x] for x in IDS])
    s = WeightSampler(IDS, prof)
    assert s.mode == "tiers"
    assert np.allclose(s.sample(40000, np.random.default_rng(0)).mean(0), centroid(4), atol=0.01)


def test_hit_and_run_gives_centroid_weights():
    prof = Profile(name="rank", tiers=[[x] for x in IDS])
    s = WeightSampler(IDS, prof)
    s.mode = "hit_and_run"
    s._setup_har()
    w = s.sample(20000, np.random.default_rng(1))
    assert np.allclose(w.mean(0), centroid(4), atol=0.015)
    assert (np.diff(w, axis=1) <= 1e-9).all()                       # order respected in every draw


def test_partial_order_and_equal_groups():
    prof = Profile(name="p", tiers=[["a"], ["b"]], equal=[["c", "d"]])
    s = WeightSampler(IDS, prof)
    assert s.mode == "hit_and_run"
    w = s.sample(5000, np.random.default_rng(2))
    assert (w[:, 0] >= w[:, 1] - 1e-9).all() and np.allclose(w[:, 2], w[:, 3]) and np.allclose(w.sum(1), 1)


SPECS = [IndicatorSpec("x", "ordinal", levels=("lo", "mid", "hi")), IndicatorSpec("y", "cardinal", bounds=(0, 10)),
         IndicatorSpec("z", "ordinal", levels=("no", "yes"))]


def test_dominance_is_certain():
    vals = {"A": {"x": "hi", "y": 7, "z": "yes"}, "B": {"x": "mid", "y": 7, "z": "yes"}}
    r = aggregate(vals, SPECS, None, K=5000)
    assert r.pairwise["A"]["B"] > 0.999


def test_symmetry():
    vals = {h: {"x": "mid", "y": 5, "z": "no"} for h in ("A", "B", "C")}
    r = aggregate(vals, SPECS, None, K=6000)
    assert max(r.p_best.values()) - min(r.p_best.values()) < 0.05


def test_unknowns_widen_spread():
    known = {"A": {"x": "mid", "y": 5, "z": "no"}, "B": {"x": "hi", "y": 2, "z": "yes"}}
    unk = {"A": {"x": None, "y": 5, "z": "no"}, "B": known["B"]}
    assert aggregate(unk, SPECS, None, K=6000).std["A"] >= aggregate(known, SPECS, None, K=6000).std["A"]


def test_monte_carlo_error_within_interval():
    vals = {"A": {"x": "hi", "y": 2, "z": "no"}, "B": {"x": "lo", "y": 9, "z": "yes"}}
    ps = [aggregate(vals, SPECS, None, K=4000, seed=s).pairwise["A"]["B"] for s in range(5)]
    half = 1.96 * math.sqrt(0.25 / 4000)
    assert max(ps) - min(ps) < 2 * half + 1e-9


def test_pool_independence_with_fixed_scales():
    base = {"A": {"x": "hi", "y": 2, "z": "no"}, "B": {"x": "lo", "y": 9, "z": "yes"}}
    more = {**base, "C": {"x": "mid", "y": 5, "z": "yes"}}
    r1, r2 = aggregate(base, SPECS, None, K=4000), aggregate(more, SPECS, None, K=4000)
    assert r1.expected["A"] == pytest.approx(r2.expected["A"]) and r1.pairwise["A"]["B"] == pytest.approx(r2.pairwise["A"]["B"])


def test_profiles_reference_known_indicators():
    ids = {s.id for s in INDICATORS}
    for p in load_profiles().values():
        for t in p.tiers:
            if t != "rest":
                assert set(t) <= ids, (p.name, set(t) - ids)

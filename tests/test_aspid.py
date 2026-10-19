"""Aggregation tests from Aggregation_Spec section 7."""
import math

import numpy as np
import pytest

from hyparena.aspid import (IndicatorSpec, InfeasiblePreferences, Prefer, Profile, WeightSampler, aggregate,
                            check_feasible, load_profiles, next_pair)
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


def _expert_pool():
    # B is better on x1, A on x2 and x3: without expert information either can win
    ind = [IndicatorSpec("x1", "cardinal"), IndicatorSpec("x2", "cardinal"),
           IndicatorSpec("x3", "ordinal", levels=("lo", "mid", "hi"), mapping="equal_steps")]
    vals = {"A": {"x1": 0.1, "x2": 0.6, "x3": "mid"}, "B": {"x1": 0.9, "x2": 0.3, "x3": "lo"},
            "C": {"x1": 0.05, "x2": 0.2, "x3": "lo"}}                    # dominated by A
    return ind, vals


def test_expert_constraint_holds():
    """Aggregation_Spec 7: after Prefer(A >= B) with no unknowns, P(u_A >= u_B) = 1."""
    ind, vals = _expert_pool()
    free = aggregate(vals, ind, None, K=4000, seed=1)
    assert 0.05 < free.pairwise["A"]["B"] < 0.95
    prof = Profile("p", prefer=[Prefer("A", "B", ">=", by="expert")])
    res = aggregate(vals, ind, prof, K=4000, seed=1)
    assert res.pairwise["A"]["B"] >= 1 - res.mc_halfwidth(1.0) - 1e-9
    assert res.meta["prefer"][0]["violated_share"] == 0.0 and not res.meta["prefer"][0]["approximate"]


def test_opposite_strict_choices_are_infeasible():
    ind, vals = _expert_pool()
    both = [Prefer("A", "B", ">", by="e1"), Prefer("B", "A", ">", by="e2"), Prefer("A", "C", ">=", by="e3")]
    feas = check_feasible(Profile("p", prefer=both), vals, ind)
    assert not feas.feasible and {(c.a, c.b) for c in feas.conflicting} == {("A", "B"), ("B", "A")}
    with pytest.raises(InfeasiblePreferences):
        aggregate(vals, ind, Profile("p", prefer=both), K=500)
    weak = [Prefer("A", "B", ">="), Prefer("B", "A", ">=")]       # equality is still admissible
    assert check_feasible(Profile("p", prefer=weak), vals, ind).feasible


def test_expert_constraint_with_unknown_is_approximate():
    ind, vals = _expert_pool()
    vals["A"]["x2"] = None
    res = aggregate(vals, ind, Profile("p", prefer=[Prefer("A", "B")]), K=2000, seed=3)
    assert res.meta["prefer"][0]["approximate"]


def test_next_pair_is_the_closest_call():
    ind, vals = _expert_pool()
    res = aggregate(vals, ind, None, K=4000, seed=1, k_top=3)
    pair = next_pair(res, threshold=0.0)
    d = lambda p: abs(res.pairwise[p[0]][p[1]] - 0.5)
    assert all(d(pair) <= d((a, b)) + 1e-12 for a in res.order for b in res.order if a != b)

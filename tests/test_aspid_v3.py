from hyparena.card import aspid_v3 as a


def _r(P, scope, I, H=None, gate="pass", feas=None):
    return ({"P": P, "scope": scope, "I": I, "headroom_I": H if H is not None else I, "gate": gate},
            {"support_share": 1.0, **({"feasibility": float(feas)} if feas is not None else {})})


def test_profiles_load_and_a_low_plausibility_is_not_compensated():
    assert set(a.load()) == {"evidence", "evolution", "funding", "frontier"}
    res = {"A": _r(0.5, "hallmark", 0.8, 1.0, feas="1"), "B": _r(0.03, "hallmark", 1.0), "C": _r(0.4, "local", 1 / 3),
           "F": _r(0.9, "organ", 0.6, gate="filtered")}
    for p in ("evidence", "funding"):
        out = a.rank(res, p, K=3000)
        assert "F" not in out.expected                         # the gate's filtered hypotheses are not ranked
        assert out.expected["A"] > out.expected["B"]
    assert a.rank(res, "evidence", K=3000).pairwise["A"]["B"] > 0.95


def test_expected_value_does_not_depend_on_the_pool():
    one = a.rank({"A": _r(0.5, "organ", 0.7)}, "evidence", K=3000).expected["A"]
    two = a.rank({"A": _r(0.5, "organ", 0.7), "B": _r(0.1, "local", 1 / 3)}, "evidence", K=3000).expected["A"]
    assert abs(one - two) < 0.02

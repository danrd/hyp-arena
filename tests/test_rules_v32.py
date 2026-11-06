import pytest

from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification
from tests.test_rules_v3 import card, claim, rec


@pytest.fixture(autouse=True)
def no_lookups(monkeypatch):
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)


def test_strength_is_continuous_and_anchored():
    assert r32.strength(0, 0)[0] == pytest.approx(0.5)
    assert r32.strength(0.6, 0)[0] == pytest.approx(5 / 6)                 # the v3 "moderate" threshold
    assert r32.strength(0.3, 0.3)[0] == pytest.approx(0.5)                  # conflict: about no record, narrower
    assert r32.strength(0.3, 0.3)[2] - r32.strength(0.3, 0.3)[1] < r32.strength(0, 0)[2] - r32.strength(0, 0)[1]
    assert r32.strength(0.1, 0)[0] < r32.strength(0.2, 0)[0] < r32.strength(0.4, 0)[0]


def test_continuous_precision_and_effect():
    assert r32.precision(None) == 0.25 and r32.precision(300) == 1.0 and 0.25 < r32.precision(30) < 1
    r = rec(1, "rct", n=100)
    r.effect_reported = "OR 4.0 (95% CI 2-8)"
    big = r32.effect_weight(r, False)
    r.effect_reported = "OR 1.3 (95% CI 1.1-1.6)"
    assert big > r32.effect_weight(r, False)


def test_two_weak_links_are_told_apart_and_a_long_invented_chain_stays_low():
    out = claim("c9", "x", "improves_healthspan_in", "human", "outcome", "outcome")
    one = card([claim("c1", "x", "activates", "y", "pathway"), out])
    a = r32.evaluate(one, [ClaimVerification(id="c1", evidence=[rec(1, "animal", n=20)])])
    b = r32.evaluate(one, [ClaimVerification(id="c1", evidence=[rec(1, "animal", n=20), rec(2, "animal", n=40)])])
    assert b.P > a.P                                                         # both "weak" in v3, apart in v3.2
    invented = card([claim(f"c{i}", "x", "activates", f"y{i}", link) for i, link in
                     enumerate(("engagement", "pathway", "effect", "effect"), 1)] + [out])
    supported = card([claim("c1", "x", "activates", "y", "engagement"), out])
    s = r32.evaluate(supported, [ClaimVerification(id="c1", evidence=[rec(1, "animal", n=40, effect="large")]),
                                 ClaimVerification(id="c9", evidence=[rec(2, "rct", n=200)])])
    assert r32.evaluate(invented, []).P < s.P / 3


def test_scope_is_not_a_factor_of_v():
    c = card([claim("c1", "x", "suppresses", "senescent cells", "pathway", hallmark="cellular_senescence"),
              claim("c9", "x", "improves_healthspan_in", "human", "outcome", "outcome")])
    res = r32.evaluate(c, [ClaimVerification(id="c1", evidence=[rec(1, "animal", n=40, effect="large")] * 2)])
    assert res.V == pytest.approx(res.P * res.I, rel=1e-3)

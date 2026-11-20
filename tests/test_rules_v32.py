import pytest

from hyparena.scoring import rules_v3 as r3
from hyparena.scoring import rules_v32 as r32
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


def test_v33_links_without_records_do_not_count_and_coverage_says_so(monkeypatch):
    monkeypatch.setattr(r32, "STEPS_SLOT", "separate")                   # history: each step its own place until v3.10
    out = claim("c9", "x", "improves_healthspan_in", "human", "outcome", "outcome")
    long_ = card([claim(f"c{i}", "x", "activates", f"y{i}", link) for i, link in enumerate(("engagement", "pathway", "effect"), 1)] + [out])
    short = card([out])
    cv = [ClaimVerification(id="c9", evidence=[rec(2, "rct", n=200)])]
    a, b = r32.evaluate(long_, cv, fold=True, neutral_unverified=True), r32.evaluate(short, cv, fold=True, neutral_unverified=True)
    assert a.P == pytest.approx(b.P) and a.coverage == pytest.approx(0.25) and b.coverage == 1.0
    assert r32.evaluate(long_, cv, fold=True).P < a.P                       # v3.2: the long chain is multiplied down
    against = [ClaimVerification(id="c1", counterevidence=[rec(3, "animal", n=40)])] + cv
    assert r32.evaluate(long_, against, fold=True, neutral_unverified=True).P < a.P   # data against still count


def test_missing_required_link_changes_support_and_coverage_only():
    step = claim("c1", "x", "activates", "y", "step")
    outcome = claim("c2", "x", "improves_healthspan_in", "human", "outcome", "outcome")
    bridge = {**claim("c3", "x", "activates", "human target", "step"), "required_for_balance": True}
    baseline = card([step, outcome])
    with_bridge = card([step, outcome, bridge])
    verifications = [
        ClaimVerification(id="c1", evidence=[rec(1, "animal", n=40)]),
        ClaimVerification(id="c2", counterevidence=[rec(2, "observational", n=200)]),
    ]
    old = r32.evaluate(baseline, verifications, v36=True)
    new = r32.evaluate(with_bridge, verifications, v36=True)
    positive = 2 * old.links["c1"][0] - 1
    negative = 2 * old.links["c2"][0] - 1
    assert positive > 0 > negative
    assert new.chain_state == pytest.approx(positive / 3 + negative / 2, abs=0.00005)
    assert new.coverage_counts == (2, 3)
    assert new.coverage == 0.6667
    assert (new.I, new.gate) == (old.I, old.gate)
    old_against = r32.evaluate(baseline, verifications[1:], v36=True)
    new_against = r32.evaluate(with_bridge, verifications[1:], v36=True)
    assert old_against.chain_state == new_against.chain_state < 0

    bridge_record = ClaimVerification(id="c3", counterevidence=[rec(3, "animal", n=40)])
    covered = r32.evaluate(with_bridge, [*verifications, bridge_record], v36=True)
    assert covered.coverage_counts == (3, 3)
    assert covered.links["c3"][0] < 0.5
    assert covered.chain_state == pytest.approx(
        (positive + negative + 2 * covered.links["c3"][0] - 1) / 3, abs=0.00005
    )


def test_required_primary_outcome_is_counted_once():
    outcome = claim("c1", "x", "improves_healthspan_in", "human", "outcome", "outcome")
    c = card([{**outcome, "required_for_balance": True}])
    result = r32.evaluate(c, [ClaimVerification(id="c1", evidence=[rec(1, "rct", n=200)])], v36=True)
    assert result.coverage_counts == (1, 1)
    assert result.chain_state > 0

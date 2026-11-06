import pytest

from hyparena import report_html as rh
from hyparena.card import rules_v3 as r3, rules_v32 as r32
from tests.test_analyze import _case


def test_p_product_reproduces_the_rules(monkeypatch):
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    c, cvs, alts = _case()
    e = r32.evaluate(c, cvs, alts, fold=True)
    S = {k: v[0] for k, v in e.links.items()}
    assert rh.p_product(c, S) == pytest.approx(e.P, rel=1e-3)
    assert rh.p_product(c, {**S, "c2": 5 / 6}) > e.P


def test_contributions_use_rank_order_centroid_weights():
    w = rh.roc_weights([["P"], ["I"], ["W", "x"]])
    assert w["P"] > w["I"] > w["W"] == w["x"] and sum(w.values()) == pytest.approx(1.0)
    assert rh.percentiles({"a": 1.0, "b": 2.0, "c": None}) == {"a": 0.25, "b": 0.75, "c": None}

from hyparena.card import rules_v3 as r3
from hyparena.card import v3_extra as x
from hyparena.card.models import ClaimVerification
from tests.test_rules_v3 import card, claim, rec


def test_extras_from_records(monkeypatch):
    monkeypatch.setattr(r3, "established_by_approval", lambda c, k: False)
    monkeypatch.setattr(x, "readiness", lambda c: 1.0)
    c = card([claim("c1", "x", "activates", "AMPK", "engagement"),
              claim("c2", "x", "improves_healthspan_in", "human", "outcome", "outcome")])
    r1, r2, r3_ = rec(1, "rct", n=120, effect="large"), rec(2, "observational", n=400, effect="small"), rec(3, "animal")
    r1.retrieved_at, r2.retrieved_at = "2019", "2010"
    cvs = [ClaimVerification(id="c2", evidence=[r1, r2], counterevidence=[r3_])]
    v3 = r3.evaluate(c, cvs).as_dict()
    e = x.extras(c, cvs, v3, as_of="2020-01-01")
    assert e["best_design_outcome"] == "rct" and e["independent_outcome"] == 2
    assert e["best_effect_outcome"] == "large" and e["human_outcome"] is True
    assert 0 < e["against_share"] < 1 and e["unverified_links"] == 1 and e["weakest_level"] == "unverified"
    assert e["momentum"] == 0.5
    assert set(x.FIRST_FOUR) <= set(e)


def test_feasibility_parts():
    c = card([claim("c2", "x", "improves_healthspan_in", "human", "outcome", "outcome")])
    c.decisive_experiment.system, c.decisive_experiment.duration_class, c.decisive_experiment.n_planned = "human", "months", 80
    import hyparena.card.v3_extra as m
    m_read = m.readiness
    try:
        m.readiness = lambda k: 1.0
        assert x.feasibility(c) == round((0 + 2 / 3 + 2 / 3 + 1) / 4, 3)
    finally:
        m.readiness = m_read

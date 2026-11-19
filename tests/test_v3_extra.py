import pytest

from hyparena.scoring import rules_v3 as r3
from hyparena.scoring import v3_extra as x
from hyparena.card.models import ClaimVerification, Intervention
from hyparena.tools import compounds
from tests.test_rules_v3 import card, claim, rec

_real_lookup = compounds.lookup


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
    import hyparena.scoring.v3_extra as m
    m_read = m.readiness
    try:
        m.readiness = lambda k: 1.0
        assert x.feasibility(c) == round((0 + 2 / 3 + 2 / 3 + 1) / 4, 3)
    finally:
        m.readiness = m_read


@pytest.mark.parametrize(("interventions", "expected"), [
    ([], (None, "unspecified")),
    ([("other", "agent")], (None, "unclassified")),
    ([("exercise", "specified exercise")], (1.0, "non_compound")),
    ([("compound", "approved")], (1.0, "approved")),
    ([("compound", "clinical")], (0.5, "clinical")),
    ([("compound", "preclinical")], (0.0, "preclinical")),
    ([("compound", "phase missing")], (None, "phase_unknown")),
    ([("compound", "not found")], (None, "unresolved")),
    ([("compound", "unavailable")], (None, "lookup_failed")),
    ([("compound", "approved + not found")], (None, "unresolved")),
    ([("compound", "approved"), ("compound", "phase missing")], (None, "phase_unknown")),
])
def test_readiness_requires_compound_match_and_phase(monkeypatch, interventions, expected):
    phases = {"approved": 4, "clinical": 2, "preclinical": 0, "phase missing": None}

    def lookup(label, *, raise_on_error):
        assert raise_on_error
        if label == "unavailable":
            raise compounds.LookupError_("simulated API failure")
        if label in phases:
            return compounds.Compound(cid=1, name=label, max_phase=phases[label])
        return None

    monkeypatch.setattr(compounds, "lookup", lookup)
    c = card([claim("c2", "x", "improves_healthspan_in", "human", "outcome", "outcome")])
    c.pico.intervention = [Intervention(type=kind, label=label) for kind, label in interventions]
    c.decisive_experiment.system, c.decisive_experiment.duration_class, c.decisive_experiment.n_planned = "human", "months", 80
    assert x.readiness_assessment(c) == expected
    assert x.readiness(c) == expected[0]
    assert x.feasibility(c) == round((4 / 3 + (expected[0] or 0)) / 4, 3)
    if expected[0] is not None:
        stated = x.feasibility(c)
        c.pico.intervention = []
        assert x.readiness_assessment(c) == (None, "unspecified")
        assert x.feasibility(c) == 0.333 <= stated


def test_compound_lookup_preserves_default_and_can_signal_failure(monkeypatch):
    def fail(_):
        raise compounds.LookupError_("simulated API failure")

    monkeypatch.setattr(compounds, "_cache", {})
    monkeypatch.setattr(compounds, "parent_cid", fail)
    monkeypatch.setattr(compounds, "lookup", _real_lookup)
    assert compounds.lookup("synthetic agent") is None
    with pytest.raises(compounds.LookupError_):
        compounds.lookup("synthetic agent", raise_on_error=True)


@pytest.mark.parametrize("n", [30, 80, 300, 1000])
@pytest.mark.parametrize("ready", [0, 0.5, 1, None])
def test_removing_empirical_sample_size_cannot_raise_feasibility(monkeypatch, n, ready):
    monkeypatch.setattr(x, "readiness", lambda _: ready)
    c = card([claim("c2", "x", "improves_healthspan_in", "human", "outcome", "outcome")])
    experiment = c.decisive_experiment
    experiment.system, experiment.duration_class, experiment.n_planned = "human", "months", n
    measured = x.feasibility(c)
    assert measured == round((2 / 3 + x._n_score(n) + (ready or 0)) / 4, 3)
    experiment.n_planned = None
    assert x.feasibility(c) <= measured
    assert x.feasibility(c) == round((2 / 3 + (ready or 0)) / 4, 3)


def test_feasibility_with_no_experiment_details():
    assert x.feasibility(card([])) == 0.0


@pytest.mark.parametrize(("system", "n", "expected"), [
    ("mouse", None, 0.0), ("cells", 0, 0.0), ("human", -2, 0.0),
    ("data_analysis", None, None), ("unknown", None, None),
])
def test_sample_size_applicability(system, n, expected):
    from hyparena.card.models import DecisiveExperiment

    assert x.sample_size_score(DecisiveExperiment(system=system, n_planned=n)) == expected

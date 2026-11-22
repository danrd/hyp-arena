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
    ([("exercise", "specified exercise")], (None, "implementation_unverified")),
    ([("device", "unspecified actuator")], (None, "implementation_unverified")),
    ([("gene", "targeted construct")], (None, "implementation_unverified")),
    ([("compound", "approved")], (1.0, "approved")),
    ([("compound", "clinical")], (0.5, "clinical")),
    ([("compound", "preclinical")], (0.0, "preclinical")),
    ([("compound", "phase missing")], (None, "phase_unknown")),
    ([("compound", "not found")], (None, "unresolved")),
    ([("compound", "wrong identity")], (None, "identity_unverified")),
    ([("compound", "phase without registry")], (None, "phase_unknown")),
    ([("compound", "unavailable")], (None, "lookup_failed")),
    ([("compound", "approved + not found")], (None, "unresolved")),
    ([("compound", "approved"), ("compound", "phase missing")], (None, "phase_unknown")),
    ([("compound", "approved"), ("device", "unspecified actuator")], (None, "implementation_unverified")),
    ([("compound", "approved + clinical")], (0.5, "clinical")),
    ([("compound", "approved + preclinical")], (0.0, "preclinical")),
    ([("compound", "approved + second approved")], (0.5, "combination_unverified")),
    ([("compound", "approved alternate name")], (1.0, "approved")),
])
def test_readiness_requires_compound_match_and_phase(monkeypatch, interventions, expected):
    phases = {"approved": 4, "clinical": 2, "preclinical": 0, "phase missing": None}

    def lookup(label, *, raise_on_error):
        assert raise_on_error
        if label == "unavailable":
            raise compounds.LookupError_("simulated API failure")
        if label == "wrong identity":
            return compounds.Compound(cid=1, name="another substance", chembl="CHEMBL1", max_phase=4)
        if label == "phase without registry":
            return compounds.Compound(cid=1, name=label, max_phase=4)
        if label == "second approved":
            return compounds.Compound(cid=2, name=label, chembl="CHEMBL2", max_phase=4)
        if label == "approved alternate name":
            return compounds.Compound(cid=1, name="approved", chembl="CHEMBL1", max_phase=4, synonyms=[label])
        if label in phases:
            return compounds.Compound(cid=1, name=label, chembl="CHEMBL1", max_phase=phases[label])
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


def test_feasibility_breakdown_matches_feasibility_and_tracks_denominator(monkeypatch):
    monkeypatch.setattr(x, "readiness_assessment", lambda _: (0.5, "clinical"))
    c = card([claim("c2", "x", "improves_healthspan_in", "human", "outcome", "outcome")])
    c.decisive_experiment.system, c.decisive_experiment.duration_class, c.decisive_experiment.n_planned = "human", "months", 80
    fb = x.feasibility_breakdown(c)
    assert fb["score"] == x.feasibility(c) == round((0 + 2 / 3 + 2 / 3 + 0.5) / 4, 3)
    assert fb["denominator"] == 4
    by_key = {p["key"]: p for p in fb["parts"]}
    assert by_key["system"] == {"key": "system", "value": "human", "score": 0.0, "in_denominator": True}
    assert by_key["duration"] == {"key": "duration", "value": "months", "score": 0.667, "in_denominator": True}
    assert by_key["sample_size"] == {"key": "sample_size", "value": 80, "score": 0.667, "in_denominator": True, "reason": "stated"}
    assert by_key["readiness"] == {"key": "readiness", "value": "clinical", "score": 0.5, "known": True, "in_denominator": True, "reason": "clinical"}

    # Missing empirical n stays in the denominator with 0; unknown readiness stays in the denominator with 0
    monkeypatch.setattr(x, "readiness_assessment", lambda _: (None, "phase_unknown"))
    c.decisive_experiment.n_planned = None
    fb2 = x.feasibility_breakdown(c)
    assert fb2["score"] == x.feasibility(c) == round((0 + 2 / 3 + 0 + 0) / 4, 3)
    assert fb2["denominator"] == 4
    by_key2 = {p["key"]: p for p in fb2["parts"]}
    assert by_key2["sample_size"]["reason"] == "missing_reserved" and by_key2["sample_size"]["score"] == 0.0
    assert by_key2["readiness"]["known"] is False and by_key2["readiness"]["score"] == 0.0

    # data_analysis with missing n excludes sample_size from the denominator
    c.decisive_experiment.system, c.decisive_experiment.duration_class, c.decisive_experiment.n_planned = "data_analysis", None, None
    fb3 = x.feasibility_breakdown(c)
    assert fb3["score"] == x.feasibility(c) == round((1.0 + 0.0) / 2, 3)
    assert fb3["denominator"] == 2
    by_key3 = {p["key"]: p for p in fb3["parts"]}
    assert by_key3["duration"]["in_denominator"] is False and by_key3["duration"]["score"] is None
    assert by_key3["sample_size"]["in_denominator"] is False and by_key3["sample_size"]["reason"] == "not_applicable"


def test_readiness_falls_back_to_clinicaltrials_with_as_of(monkeypatch):
    from hyparena.tools import clinicaltrials

    monkeypatch.setattr(compounds, "lookup", lambda label, raise_on_error=False: None)
    monkeypatch.setattr(
        clinicaltrials,
        "compound_phase",
        lambda label, as_of="": {"matched": True, "max_phase": 2, "ncts": ["NCT06414954"]}
        if label == "NMD670" else {"matched": False, "max_phase": None, "ncts": []},
    )
    c = card([claim("c2", "x", "improves_healthspan_in", "human", "outcome", "outcome")])
    c.pico.intervention = [Intervention(type="compound", label="NMD670")]
    c.decisive_experiment.system, c.decisive_experiment.duration_class, c.decisive_experiment.n_planned = "human", "months", 80
    # Without as_of, stays offline / ChEMBL-only
    assert x.readiness_assessment(c) == (None, "unresolved")
    # With as_of, falls back to ClinicalTrials.gov up to as_of
    assert x.readiness_assessment(c, as_of="2026-11-19") == (0.5, "ct_clinical")
    assert x.feasibility(c, as_of="2026-11-19") == round((0 + 2 / 3 + 2 / 3 + 0.5) / 4, 3)
    fb = x.feasibility_breakdown(c, as_of="2026-11-19")
    assert fb["score"] == x.feasibility(c, as_of="2026-11-19")
    assert next(p for p in fb["parts"] if p["key"] == "readiness")["reason"] == "ct_clinical"


def test_endpoint_for_experiment_caps_nonhuman_systems():
    assert x.endpoint_for_experiment("clinical_event", "human") == "clinical_event"
    assert x.endpoint_for_experiment("function", "human") == "function"
    assert x.endpoint_for_experiment("clinical_event", "mouse") == "biomarker"
    assert x.endpoint_for_experiment("function", "cells") == "biomarker"
    assert x.endpoint_for_experiment("patient_reported", "rat") == "biomarker"
    assert x.endpoint_for_experiment("biomarker", "cells") == "biomarker"
    assert x.endpoint_for_experiment(None, "cells") is None

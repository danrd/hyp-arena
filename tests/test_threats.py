"""v3.11: the fixed checklist of methodological threats per system and its part in informativeness I."""
from hyparena.alternatives import threats
from hyparena.card.models import Claim, Entity, HypothesisCard, ProposedAlternative
from hyparena.scoring import rules_v32 as r32


def _card(system="human", design="rct", control="placebo", registry=None, alternatives=()):
    card = HypothesisCard.model_validate({
        "id": "t", "raw_id": "t", "hypothesis_type": "interventional", "claim_plain": "x",
        "pico": {"population": {"taxon": "NCBITaxon:9606", "label": "older adults"}, "intervention": [{"type": "compound", "label": "x"}],
                 "outcome": {"endpoint": "healthspan", "metric": "gait speed", "direction": "improve"}},
        "claims": []})
    card.claims.append(Claim(id="c1", subject=Entity(label="x"), relation="promotes", object=Entity(label="gait speed"),
                             source_span="x", link="outcome", role="outcome"))
    e = card.decisive_experiment
    e.system, e.design, e.control, e.registry = system, design, control, registry or {}
    card.proposed_alternatives = list(alternatives)
    return card


def _alt(i, obj):
    return ProposedAlternative.model_validate({"id": f"p{i}", "subject": {"label": "the trial"}, "relation": "promotes",
                                               "object": {"label": obj}, "on_positive": "eliminated", "on_negative": "unchanged"})


BLIND_RCT = {"allocation": "randomized", "model": "parallel", "masked": ["participant", "outcomes assessor"],
             "arms": [{"type": "experimental"}, {"type": "placebo comparator"}]}


def test_a_blinded_placebo_rct_cuts_off_five_threats_and_weakens_two():
    ck = threats.checklist(_card(registry=BLIND_RCT))
    assert ck["system"] == "human" and ck["share"] == 0.75
    assert {o["threat"] for o in ck["open"]} == {"selection", "cointervention", "multiplicity"}


def test_a_single_group_rules_out_nothing_and_masking_not_stated_is_not_masked():
    assert threats.checklist(_card(design="single_arm", control="none"))["share"] == 0.0
    ck = threats.checklist(_card())                    # card fields only: randomised placebo control, masking unknown
    assert ck["threats"]["assessor"] == "unchanged" and ck["threats"]["practice"] == "eliminated"


def test_cells_and_animals_do_not_tell_apart_and_name_the_fix():
    for sys_name in ("cells", "in_vitro"):
        ck = threats.checklist(_card(system=sys_name))
        assert ck["system"] == "cells" and ck["share"] == 0.0 and len(ck["open"]) == 6
        assert "second tool" in next(o["fix"] for o in ck["open"] if o["threat"] == "off_target")
    assert threats.checklist(_card(system="mouse"))["system"] == "animal"
    assert threats.checklist(_card(system="unknown")) is None


def test_methodological_alternatives_are_recognised_by_their_words():
    assert threats.is_methodological(_alt(1, "regression to the mean in gait speed"))
    assert threats.is_methodological(_alt(2, "practice effect on repeated testing"))
    assert not threats.is_methodological(_alt(3, "weight loss improves gait speed"))


def test_the_checklist_counts_in_I_as_one_alternative_of_support_one_half():
    card = _card(registry=BLIND_RCT, alternatives=[_alt(1, "regression to the mean in gait speed")])
    e = r32.evaluate(card, [], {}, v36=True)
    assert e.I == round(0.5 * 0.75 / 1.5, 4) and e.headroom_I == round(0.5 / 1.5, 4)
    assert e.checklist["share"] == 0.75


def test_threat_checklist_off_gives_the_earlier_I(monkeypatch):
    monkeypatch.setattr(r32, "THREAT_CHECKLIST", False)
    e = r32.evaluate(_card(registry=BLIND_RCT), [], {}, v36=True)
    assert e.I == 0.0 and e.checklist is None

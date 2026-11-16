"""Novelty is measured on the main factor's effect: an outcome claim whose subject is a later step is a step for N."""
from hyparena.card.models import Claim, Entity, HypothesisCard
from hyparena.novelty import novelty_v34 as nv


def _card(outcome_subject: str, intervention: str = "NMNAT2 delivery intervals"):
    card = HypothesisCard.model_validate({"id": "t", "raw_id": "t", "hypothesis_type": "mechanistic", "claim_plain": "x",
                                          "pico": {"intervention": [{"type": "procedure", "label": intervention}]}, "claims": []})
    card.claims = [Claim(id="c1", subject=Entity(label=intervention), relation="suppresses", object=Entity(label="local NMNAT2 activity"),
                         source_span="x", link="step"),
                   Claim(id="c2", subject=Entity(label="local NMNAT2 activity drop"), relation="activates", object=Entity(label="SARM1"),
                         source_span="x", link="step"),
                   Claim(id="c3", subject=Entity(label=outcome_subject), relation="promotes", object=Entity(label="axon destruction"),
                         source_span="x", link="outcome", role="outcome")]
    return card


def test_a_known_end_of_the_chain_is_not_the_outcome_of_novelty():
    card = _card("SARM1")
    assert not nv._is_main_factor(card, card.claims[2])          # SARM1 is the object of the step before


def test_the_main_factor_or_an_unknown_subject_stays_the_outcome():
    card = _card("NMNAT2 delivery intervals")
    assert nv._is_main_factor(card, card.claims[2])
    card = _card("rapamycin")                                     # a renamed main factor: never moved (it would look newer)
    assert nv._is_main_factor(card, card.claims[2])

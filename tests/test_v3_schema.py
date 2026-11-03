"""Method v3: schema additions are optional (v2 cards and records still load) and level weights follow i/k."""
import json

import pytest

from hyparena.card import v3_levels as lv
from hyparena.card.models import EvidenceRecord, HypothesisCard, ProposedAlternative
from tests.test_benchmark_run import PILOT_CARD


def test_v2_card_and_record_still_load_with_v3_defaults():
    card = HypothesisCard.model_validate(json.loads(json.dumps(PILOT_CARD)))
    assert card.claims[0].link is None and card.proposed_alternatives == [] and card.decisive_experiment.design == "unknown"
    rec = EvidenceRecord.model_validate({"source": "PubMed", "record_id": "PMID:1"})
    assert rec.design == "unknown" and rec.n_total is None and rec.effect_class == "unclear"


def test_v3_fields_round_trip():
    d = json.loads(json.dumps(PILOT_CARD))
    d["claims"][0]["link"] = "outcome"
    d["decisive_experiment"].update(design="rct", control="placebo", n_planned=120, primary_outcome="heat storage")
    d["proposed_alternatives"] = [{"id": "p1", "subject": {"label": "fitness"}, "relation": "associated_with",
                                   "object": {"label": "heat storage"}, "support_pmids": ["123"],
                                   "on_positive": "weakened", "on_negative": "unchanged"}]
    card = HypothesisCard.model_validate(d)
    again = HypothesisCard.model_validate(json.loads(card.model_dump_json(by_alias=True)))
    assert again.claims[0].link == "outcome" and again.decisive_experiment.n_planned == 120
    assert again.proposed_alternatives[0].support_pmids == ["123"]


def test_an_alternative_cannot_be_eliminated_by_both_outcomes():
    with pytest.raises(ValueError):
        ProposedAlternative.model_validate({"id": "p1", "subject": {"label": "a"}, "relation": "other", "object": {"label": "b"},
                                            "on_positive": "eliminated", "on_negative": "eliminated"})


def test_level_weights_are_equal_steps():
    assert lv.weight("effect", "none") == 0.25 and lv.weight("effect", "large") == 1.0 and lv.weight("effect", "unclear") == 0.5
    assert lv.weight("design_human", "rct") == 1.0 and lv.weight("design_human", "cells") == pytest.approx(1 / 7)
    assert lv.weight("design_human", "review") < lv.weight("design_human", "non_randomised") < lv.weight("design_human", "rct")
    assert lv.weight("link", "unverified") == 0.5 and lv.weight("discrimination", "unchanged") == 0.0
    assert lv.precision_band(None) == "lt30" and lv.precision_band(737) == "ge300"
    assert lv.design_weight("rct", human_claim=False) == 1.0 and lv.design_weight("other", human_claim=True) == pytest.approx(1 / 7)
    with pytest.raises(ValueError):
        lv.weight("context", "unknown")

import pytest

from hyparena.card import rules_v3 as r3, rules_v32 as r32
from hyparena.card.models import ClaimVerification, HypothesisCard
from tests.test_rules_v3 import claim, rec


def _card(primary_outcome, roles=("outcome", "premise", "premise")):
    claims = [claim("c1", "squats", "improves_healthspan_in", "human", "outcome", roles[0]),
              claim("c2", "squats", "changes_biomarker", "body composition", "outcome", roles[1]),
              claim("c3", "squats", "suppresses", "pre-sarcopenia", "outcome", roles[2])]
    return HypothesisCard.model_validate({"id": "H-1", "hypothesis_type": "interventional", "claim_plain": "x", "claims": claims,
                                          "decisive_experiment": {"primary_outcome": primary_outcome}})


@pytest.fixture(autouse=True)
def _no_approval(monkeypatch):
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)


def test_an_empty_parallel_outcome_does_not_pull_the_slot(monkeypatch):
    card = _card("Short Physical Performance Battery; Body composition assessed by InBody")
    cvs = [ClaimVerification(id="c1", evidence=[rec(1, "rct", n=300, effect="large")]),
           ClaimVerification(id="c3", evidence=[rec(2, "rct", n=300, effect="large")])]
    e = r32.evaluate(card, cvs, {}, v36=True)
    S1 = e.links["c1"][0]
    assert e.chain_state == pytest.approx(2 * S1 - 1, abs=1e-3)       # c2 (no records) is not averaged in
    refuted = [ClaimVerification(id="c1", counterevidence=[rec(3, "rct", n=400, effect="none")])]
    e2 = r32.evaluate(card, refuted, {}, v36=True)
    assert e2.chain_state == pytest.approx(2 * e2.links["c1"][0] - 1, abs=1e-3)   # nor softens a refuted one


def test_the_card_outcome_is_primary_only_with_a_single_registry_outcome():
    single = _card("Short Physical Performance Battery")                 # no word of it matches the claims' labels
    outs, primary = r3.outcome_group(single, r3.chain(single))
    assert primary is not None and primary.id == "c1"
    two = _card("Physical performance; Body composition")
    outs, primary = r3.outcome_group(two, r3.chain(two))
    assert primary is None

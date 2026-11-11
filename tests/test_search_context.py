from hyparena.card import llm
from hyparena.card.models import Claim, HypothesisCard
from hyparena.card.search import ALTERNATIVE_NOTE, model_queries
from hyparena.card.verifier import queries

CARD = HypothesisCard.model_validate({
    "id": "H-1", "hypothesis_type": "interventional", "claim_plain": "Squats improve SPPB in pre-sarcopenia.",
    "pico": {"population": {"label": "older adults with pre-sarcopenia"}, "intervention": [{"type": "other", "label": "squat exercise"}],
             "outcome": {"endpoint": "healthspan", "metric": "SPPB; body composition"}},
    "claims": [{"id": "c1", "subject": {"label": "squat exercise"}, "relation": "improves_healthspan_in", "object": {"label": "human"},
                "role": "outcome", "link": "outcome", "source_span": "x"}]})


def _seen(monkeypatch):
    seen = {}

    def fake_ask(client, **k):
        seen.update(k["variables"])
        return {"queries": ["a"]}, "f"
    monkeypatch.setattr(llm, "ask", fake_ask)
    return seen


def test_an_alternative_is_searched_on_its_own_terms(monkeypatch):
    seen = _seen(monkeypatch)
    alt = Claim(id="p2", subject={"label": "attention and supervision"}, relation="improves_healthspan_in",
                object={"label": "physical performance"}, role="premise", source_span="", note=ALTERNATIVE_NOTE)
    model_queries(None, "f", frozenset(), alt, CARD, "2026-11-06")
    assert seen["intervention"] == "attention and supervision" and seen["outcome"] == "physical performance"
    assert "squat" not in seen["claim_plain"].lower()


def test_a_hypothesis_claim_keeps_the_hypothesis_context(monkeypatch):
    seen = _seen(monkeypatch)
    model_queries(None, "f", frozenset(), CARD.claims[0], CARD, "2026-11-06")
    assert seen["intervention"] == "squat exercise" and seen["claim_plain"].startswith("Squats")


def test_keyword_queries_add_lifespan_only_to_lifespan_claims():
    assert not any("lifespan" in q for q in queries(CARD.claims[0], CARD))
    life = Claim(id="c9", subject={"label": "squat exercise"}, relation="extends_lifespan_in", object={"label": "mouse"},
                 role="premise", source_span="")
    assert any("lifespan" in q for q in queries(life, CARD))

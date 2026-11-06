from hyparena.card.models import HypothesisCard
from hyparena.card.normalizer import registry_defaults

REG = "A trial registered to test the following.\nConditions: Frailty; Aging\nSummary: an adaptive app chooses each next exercise dose."


def _card(rel="promotes", **kw):
    return HypothesisCard.model_validate({"id": "H", "hypothesis_type": "interventional", "claim_plain": "x", **kw,
                                          "claims": [{"id": "c1", "subject": {"label": "x"}, "relation": rel,
                                                      "object": {"label": "function"}, "role": "outcome", "source_span": "x"}]})


def test_endpoint_and_population_from_the_registry_text():
    c = _card()
    assert len(registry_defaults(c, REG)) == 2
    assert c.pico.outcome.endpoint == "healthspan" and c.pico.population.taxon == "NCBITaxon:9606"
    c = _card("changes_biomarker")
    registry_defaults(c, "Free text, not a registry entry.")
    assert c.pico.outcome.endpoint == "biomarker" and c.pico.population.label == "unknown"   # no registry: no population


def test_ai_role_needs_a_verbatim_span():
    c = _card(ai_role="in_the_loop", ai_role_span="an adaptive app chooses each next exercise dose")
    registry_defaults(c, REG)
    assert c.ai_role == "in_the_loop"
    c = _card(ai_role="intervention", ai_role_span="uses deep learning")
    registry_defaults(c, REG)
    assert c.ai_role == "none" and c.ai_role_span == ""

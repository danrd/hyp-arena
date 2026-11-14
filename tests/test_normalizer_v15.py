"""normalize_card/v15: code parts (docs/system/card.md, "Звенья: как определяется тип")."""
from hyparena.card.models import HypothesisCard
from hyparena.card.normalizer import age_class, primary_from_registry, v15_prepare, v15_problems, derive_roles


def _card(claims, main="squat exercise", interventions=("squat exercise",)):
    return HypothesisCard.model_validate({
        "id": "T", "hypothesis_type": "interventional", "claim_plain": "x",
        "main_factor": {"label": main, "kind": "intervention"},
        "pico": {"intervention": [{"label": i} for i in interventions]},
        "claims": claims})


def _c(i, s, o, link=None, part=None, level=None, measure=None, primary=False):
    d = {"id": i, "subject": {"label": s}, "relation": "promotes", "object": {"label": o}, "source_span": s,
         "link": link, "part": part, "level": level, "primary": primary, "stated_as": "claimed"}
    if measure:
        d["qualifiers"] = {"measure": measure}
    return d


def test_age_class_mesh_groups():
    assert age_class("older adults") == "Aged"
    assert age_class("65-85 years") == "Aged; Aged, 80 and over"
    assert age_class("45 to 64 years") == "Middle Aged"
    assert age_class("oldest old") == "Aged, 80 and over"
    assert age_class("20 months", "NCBITaxon:10090") == ""      # animals: their own scale, not MeSH human groups
    assert age_class("unknown") == ""


def test_premise_is_off_the_chain_and_main_outcome_from_registry():
    card = _card([_c("c1", "squat exercise", "pre-sarcopenia", "outcome", "chain", "organism", primary=True),
                  _c("c2", "squat exercise", "physical performance", "outcome", "chain", "organism"),
                  _c("c3", "pre-sarcopenia", "older adults", "pathway", "premise", "organism")])
    v15_prepare(card)
    assert card.claims[2].link is None
    text = "A trial registered to test the following.\nPrimary outcomes: Physical performance assessed by the SPPB (12 weeks)"
    assert primary_from_registry(card, text) == []
    assert [c.primary for c in card.claims] == [False, True, False]
    derive_roles(card)
    assert card.claims[1].role == "outcome" and card.claims[2].role == "premise"


def test_missing_registry_primary_is_sent_back():
    card = _card([_c("c1", "squat exercise", "pre-sarcopenia", "outcome", "chain", "organism", primary=True)])
    out = primary_from_registry(card, "Primary outcomes: Body composition by InBody (12 weeks)")
    assert out and "Body composition" in out[0]


def test_v15_problems():
    card = _card([_c("c1", "squat exercise", "muscle mass", "pathway", "chain", "tissue"),
                  _c("c2", "loneliness", "cognitive decline", "pathway", "chain", "organism"),
                  _c("c3", "приседания", "сила", "outcome", "chain", "organism"),
                  _c("c4", "muscle mass", "physical performance", "outcome", "chain", "organism")])
    probs = " | ".join(v15_problems(card))
    assert "c1: link pathway with level tissue" in probs              # a tissue state is an effect
    assert "c2: part chain, but its subject" in probs                 # not the main factor, nor an earlier step
    assert "c3: write subject, object and measure labels in English" in probs
    assert "c4" not in probs                                          # follows from c1's object


def test_other_labels_in_english():
    card = _card([_c("c1", "squat exercise", "muscle mass", "effect", "chain", "tissue")])
    card.decisive_experiment.arms = ["контрольный пептид"]
    assert any("arms[0]: write it in English" in p for p in v15_problems(card))


def test_registry_arms_with_a_colon_in_the_label():
    from hyparena.card.normalizer import registry_design
    t = ("Arms: Squat Exercise (experimental): A 12-week squat exercise intervention is implemented.; "
         "Intervention: Usual Care (no intervention): No specific resistance training.")
    arms = registry_design(t)["arms"]
    assert [a["type"] for a in arms] == ["experimental", "no intervention"] and arms[1]["label"] == "Intervention: Usual Care"

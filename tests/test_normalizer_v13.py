"""normalize_card/v13 (2026-11-12): role derived from primary / stated_as, background, code fields of the experiment."""
from hyparena.card.models import HypothesisCard
from hyparena.card.normalizer import author_refs, derive_roles, duration_class, registry_design, v13_code_fields
from hyparena.card.rules import core_span_problems, validate_card

TEXT = ("A trial registered to test the following.\nConditions: Sarcopenia\n"
        "Summary: whey protein with regular physical activity would increase muscle mass and strength in sarcopenic elderly "
        "over 12 weeks, compared with an isocaloric placebo, because leucine activates mTORC1.\n"
        "Design: randomized, parallel, masking double (participant, investigator), primary purpose treatment\n"
        "Arms: supplement (experimental): whey protein; placebo (placebo comparator): maltodextrin\n"
        "Planned enrollment: 80\nPrimary outcomes: muscle mass (12 weeks)")


def _card():
    claim = lambda i, link, prim, st, span, obj: {"id": i, "subject": {"label": "whey protein"}, "relation": "promotes",
                                                  "object": {"label": obj}, "link": link, "primary": prim, "stated_as": st,
                                                  "level": "tissue", "role": "premise", "source_span": span}
    return HypothesisCard.model_validate({
        "id": "t", "hypothesis_type": "interventional", "claim_plain": "x",
        "pico": {"population": {"label": "sarcopenic elderly", "span": "sarcopenic elderly"},
                 "intervention": [{"type": "diet", "label": "whey protein", "span": "whey protein"}],
                 "background": [{"type": "procedure", "label": "physical activity", "span": "regular physical activity"}],
                 "comparator": {"type": "placebo", "label": "isocaloric placebo", "span": "an isocaloric placebo"},
                 "outcome": {"metric": "muscle mass", "direction": "increase", "span": "increase muscle mass"}},
        "claims": [claim("c1", "engagement", False, "claimed", "leucine activates mTORC1", "mTORC1"),
                   claim("c2", "outcome", True, "claimed", "increase muscle mass", "muscle mass"),
                   claim("c3", "outcome", False, "claimed", "strength", "strength")],
        "decisive_experiment": {"system": "human", "design": "rct", "primary_outcomes": ["muscle mass (12 weeks)"],
                                "duration": "12 weeks", "span": "randomized, parallel, masking double"}})


def test_roles_are_derived_from_primary_and_stated_as():
    card = _card()
    derive_roles(card)
    assert [c.role for c in card.claims] == ["mechanism", "outcome", "premise"]
    assert not any("role outcome" in p for p in validate_card(card, TEXT))   # exactly one outcome claim


def test_no_primary_given_the_first_outcome_link_is_the_main_one():
    card = _card()
    for c in card.claims:
        c.primary = False
    derive_roles(card)
    assert card.outcome_claim.id == "c2"


def test_code_fields_of_the_experiment():
    card = _card()
    v13_code_fields(card, TEXT)
    e = card.decisive_experiment
    assert e.control == "placebo" and e.duration_class == "weeks" and e.primary_outcome == "muscle mass (12 weeks)"
    assert e.n_planned == 80 and e.registry["masked"] == ["participant", "investigator"]
    assert [a["type"] for a in e.registry["arms"]] == ["experimental", "placebo comparator"]


def test_background_spans_are_checked_like_the_other_core_fields():
    card = _card()
    assert core_span_problems(card, TEXT) == []
    card.pico.background[0].span = "a supervised gym programme"
    assert any("pico.background[0]" in p for p in core_span_problems(card, TEXT))


def test_duration_class_and_references():
    assert [duration_class(x) for x in ("12 weeks", "24 weeks", "2 years", "")] == ["weeks", "months", "years", "unknown"]
    assert author_refs("as shown (PMID: 30414822)") == ["PMID:30414822"]
    assert registry_design("no design lines") == {}

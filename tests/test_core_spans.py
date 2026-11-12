"""normalize_card/v12 (2026-11-12): the core fields of the card carry a verbatim span, checked like the spans of claims."""
from hyparena.card.models import HypothesisCard
from hyparena.card.rules import anchor_core, core_span_problems, validate_card

TEXT = ("A trial registered to test the following.\nConditions: Sarcopenia\n"
        "Summary: whey protein and vitamin D with regular physical activity would increase muscle mass in sarcopenic elderly, "
        "compared with an isocaloric placebo, in a randomized, double-blind, placebo-controlled trial.")


def _card(**over):
    d = {"id": "t", "hypothesis_type": "interventional", "claim_plain": "x",
         "pico": {"population": {"label": "sarcopenic elderly", "span": "sarcopenic elderly"},
                  "intervention": [{"type": "diet", "label": "whey protein and vitamin D", "span": "whey protein and vitamin D"}],
                  "comparator": {"type": "placebo", "label": "isocaloric placebo", "span": "an isocaloric placebo"},
                  "outcome": {"endpoint": "healthspan", "metric": "muscle mass", "span": "increase muscle mass"}},
         "claims": [{"id": "c1", "subject": {"label": "whey protein"}, "relation": "promotes", "object": {"label": "muscle mass"},
                     "role": "outcome", "link": "outcome", "source_span": "would increase muscle mass"}],
         "decisive_experiment": {"design": "rct", "control": "placebo", "span": "randomized, double-blind, placebo-controlled"}}
    for k, v in over.items():
        d["pico"][k] = v
    return HypothesisCard.model_validate(d)


def test_verbatim_core_spans_pass():
    card = _card()
    assert core_span_problems(card, TEXT) == []
    assert anchor_core(card, TEXT) == [] and card.unanchored == []


def test_a_span_not_in_the_text_is_a_problem_and_is_cleared_after_the_rounds():
    card = _card(comparator={"type": "placebo", "label": "maltodextrin", "span": "a maltodextrin placebo"})
    probs = core_span_problems(card, TEXT)
    assert any(p.startswith("core pico.comparator: span is not a verbatim") for p in probs)
    assert anchor_core(card, TEXT) == ["pico.comparator"]
    assert card.pico.comparator.span == "" and card.pico.comparator.label == "maltodextrin"   # the value is kept


def test_a_known_field_without_a_span_is_a_problem_an_unknown_one_is_not():
    card = _card(outcome={"endpoint": "healthspan", "metric": "muscle mass"},
                 comparator={"type": "unknown", "label": "unknown"})
    probs = core_span_problems(card, TEXT)
    assert probs == ["core pico.outcome: span is missing (copy the exact phrase of the text that states it)"]


def test_cards_before_v12_are_not_checked_for_core_spans():
    card = _card(outcome={"endpoint": "healthspan", "metric": "muscle mass"})
    assert not any(p.startswith("core ") for p in validate_card(card, TEXT))   # validate_card itself does not ask for them

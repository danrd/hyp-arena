from scripts.normalizer_prompt_check2 import adopt, descriptor_words, has_descriptor_claim
from scripts.normalizer_prompt_check import FACETS


def _card(*claims):
    return {"claims": [{"role": r, "source_span": s, "subject": {"label": "X"}, "relation": "r", "object": {"label": o}} for r, s, o in claims]}


def test_descriptor_claim_is_a_non_outcome_claim_built_on_a_bracketed_word():
    text = "Diet INT-767d (FXR/TGR5 agonist) 180 ppm food, start 10 mo -> longer lifespan"
    assert descriptor_words(text) == {"fxr", "tgr5", "agonist"}
    assert has_descriptor_claim(_card(("premise", "INT-767d (FXR/TGR5 agonist)", "FXR"), ("outcome", "longer lifespan", "mouse")), text)
    assert not has_descriptor_claim(_card(("outcome", "INT-767d (FXR/TGR5 agonist) lifespan", "mouse")), text)
    assert not has_descriptor_claim(_card(("premise", "x", "AMPK")), "Metformin 30 ppm food")


def _m(**kw):
    m = {"failed": 0, "descriptor_claim_cards": 2, "outcome_first": 13, "agree_subject": 11, "unresolved_rate": 0.2, "mean_facet_agreement": 0.9}
    m.update(kw)
    return m


def test_adoption_allows_one_card_of_noise_but_needs_a_gain_of_three_and_the_guard():
    guard = {f: 0.9 for f in FACETS}
    better = _m(descriptor_claim_cards=0, outcome_first=15, agree_subject=14)
    assert adopt([_m(), _m()], [better, better], guard, guard)["adopt"] is True
    one_worse = better | {"outcome_first": 12}                   # one card below v5 is within the tolerance
    assert adopt([_m(), _m()], [one_worse, better], guard, guard)["worse_on"] == []
    assert adopt([_m(), _m()], [better | {"outcome_first": 11}, better], guard, guard)["adopt"] is False
    assert adopt([_m(), _m()], [_m(), _m()], guard, guard)["adopt"] is False        # no gain
    assert adopt([_m(), _m()], [better, better], {f: 0.7 for f in FACETS}, guard)["adopt"] is False

from scripts.normalizer_prompt_check import FACETS, adopt, main_claim, measures


def _card(role="outcome", subject="x", n=1, dose="30 ppm food"):
    claims = [{"role": role, "subject": {"label": subject}, "relation": "extends_lifespan_in", "object": {"label": "mouse"}, "qualifiers": {"dose": dose}}]
    claims += [{"role": "premise", "subject": {"label": subject}, "relation": "activates", "object": {"label": "FXR"}, "qualifiers": {}} for _ in range(n - 1)]
    return {"claims": claims}


def test_main_claim_is_the_outcome_claim_even_when_it_is_listed_last():
    c = {"claims": [{"role": "premise"}, {"role": "outcome"}]}
    assert main_claim(c)["role"] == "outcome"


def test_measures_count_first_outcome_claim_claim_count_and_facets():
    ref = [_card(), _card(subject="y")]
    cards = [_card(), _card(role="premise", subject="z", n=3)]
    m = measures(cards, ref, [0, 1])
    assert m["unresolved"] == 1 and m["outcome_first"] == 1 and m["same_claim_count"] == 1 and m["agree_subject"] == 1


def test_adoption_needs_no_regression_a_gain_of_two_items_and_the_guard():
    ok = {f"agree_{f}": 10 for f in FACETS} | {"unresolved": 0, "outcome_first": 14, "same_claim_count": 12, "mean_facet_agreement": 0.7}
    worse = ok | {"outcome_first": 11}
    base = ok | {"outcome_first": 12, "same_claim_count": 11, "agree_subject": 8, "mean_facet_agreement": 0.65, "unresolved": 3}
    guard = {f: 0.9 for f in FACETS}
    assert adopt([base, base], [ok, ok], guard, guard)["adopt"] is True
    assert adopt([base, base], [worse, ok], guard, guard)["adopt"] is False          # a measure got worse
    assert adopt([base, base], [ok, ok], {f: 0.7 for f in FACETS}, guard)["adopt"] is False   # the original-text guard fails
    assert adopt([ok, ok], [ok, ok], guard, guard)["adopt"] is False                 # no gain

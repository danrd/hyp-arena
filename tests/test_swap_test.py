import pytest
from hyparena.tools.swap_test import swap_variants, prior_bias_score, rank_shift

def stub_insensitive(text: str) -> float:
    # return a score based on a hash or length so it's not identical for all, but insensitive to name swaps
    return float(len(text.replace("Compound_42", "").replace("rapamycin", "").replace("sirolimus", "").replace("acarbose", "")))

def stub_biased(text: str) -> float:
    return 1.5 if "rapamycin" in text.lower() else 0.5

def test_swap_variants_basic():
    text = "Rapamycin is a drug, also known as sirolimus. But rapamycinol is not."
    variants = swap_variants(text, name="rapamycin", aliases=("sirolimus",))

    assert variants.own == text
    assert variants.count_neutral == 2
    assert variants.count_famous == 2

    assert "Compound_42 is a drug, also known as Compound_42." in variants.neutral
    assert "rapamycinol" in variants.neutral

    assert "rapamycin is a drug, also known as rapamycin." in variants.famous
    assert "rapamycinol" in variants.famous

def test_prior_bias_score_insensitive():
    def pure_stub(text: str) -> float:
        return 0.5

    items = [
        ("Rapamycin is good", "rapamycin", ()),
        ("Something else", "something", ())
    ]
    bias = prior_bias_score(pure_stub, items)

    assert bias.mean_neutral_minus_own == 0.0
    assert bias.mean_famous_minus_own == 0.0

    assert bias.ci_neutral[0] <= 0.0 <= bias.ci_neutral[1]
    assert bias.ci_famous[0] <= 0.0 <= bias.ci_famous[1]
    assert bias.n_items == 2

def test_prior_bias_score_biased():
    items = [
        ("Sirolimus works well.", "rapamycin", ("sirolimus",)),
        ("Acarbose works well.", "acarbose", ()),
        ("Nothing to see here.", "nothing", ())
    ]
    # For Sirolimus:
    # own: "Sirolimus works well." (no rapamycin) -> 0.5
    # neutral: "Compound_42 works well." (no rapamycin) -> 0.5
    # famous: "rapamycin works well." (has rapamycin) -> 1.5

    bias = prior_bias_score(stub_biased, items)

    assert bias.mean_neutral_minus_own == 0.0
    assert bias.mean_famous_minus_own == 1.0

    # Check that CI excludes 0 for famous
    assert bias.ci_famous[0] > 0.0

def test_rank_shift_insensitive():
    # To test rank_shift being 1.0, we need a component that scores items consistently
    # regardless of whether the text has the famous name or not.
    # The component should order the items.
    item_base_scores = {
        "A": 10.0,
        "B": 20.0,
        "C": 30.0,
        "D": 40.0
    }

    def rank_stub(text: str) -> float:
        # extract the base identifier from the text
        for k, v in item_base_scores.items():
            if k in text:
                return v
        return 0.0

    items = [
        ("Text A about sirolimus", "rapamycin", ("sirolimus",)),
        ("Text B about acarbose", "acarbose", ()),
        ("Text C about aspirin", "aspirin", ()),
        ("Text D about metformin", "metformin", ())
    ]

    tau, (ci_low, ci_high) = rank_shift(rank_stub, items)

    assert tau == 1.0
    assert ci_low == 1.0
    assert ci_high == 1.0

"""The effect-phrase parser extensions (specs/scoring/effect-phrase-2026-11-15.yaml): off by default, and what each reads."""
import pytest

from hyparena.reading import effect_class as ec


@pytest.fixture
def on():
    def switch(*names):
        ec.EXTRA = frozenset(names)
    yield switch
    ec.EXTRA = frozenset()


def test_extensions_are_off_by_default():
    assert ec.EXTRA == frozenset()
    assert ec.d_extra("0.86 points on the SPPB scale (95% CI 0.32, 1.41)", 188, "between_groups") is None
    assert ec.class_two_values("45% vs 27%") == "unclear"
    assert ec.d_from_p("p = 0.002", 91, "between_groups") is None


def test_interval_with_unit_words_braces_and_smd(on):
    on("interval")
    assert ec.d_extra("0.86 points on the SPPB scale (95% CI 0.32, 1.41)", 188, "between_groups") == pytest.approx(0.45, abs=0.01)
    assert ec.d_extra("46 m {20;72}", 40, "within_group") == pytest.approx(0.55, abs=0.01)
    assert ec.d_extra("SMD final value: 0.18; 95% CI: 0.05, 0.30", None, "between_groups") == pytest.approx(0.18)
    assert ec.d_extra("2.4 kg (95% C.I. = 1.2-3.6)", None, "between_groups") is None          # no n, no d
    assert ec.d_extra("22.6% (9.5%)", 302, "between_groups") is None


def test_two_means_with_spread_but_not_one(on):
    on("means")
    assert ec.d_extra("pre 14.1 ± 3.2 and post 17.5 ± 3.6", 15, "within_group") == pytest.approx(1.0, abs=0.01)
    assert ec.d_extra("8.96 ± 24 W", 48, "between_groups") is None


def test_two_values(on):
    on("two_values")
    assert ec.class_two_values("homocysteine decreased from 14.7 to 9.5 micromol/l") == "large"
    assert ec.class_two_values("45% vs 27%") == "medium"
    assert ec.class_two_values("+6.6 s versus -2.0 s") == "unclear"                             # opposite signs
    assert ec.class_two_values("3.90+/-2.30 vs -0.79+/-4.18 kg") == "unclear"                   # a spread is not a value


def test_p_value_with_n(on):
    on("p_value")
    assert ec.d_from_p("p = 0.002", 91, "between_groups") == pytest.approx(0.65, abs=0.01)
    assert ec.d_from_p("p = 0.002", None, "between_groups") is None

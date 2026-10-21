"""late_start (card spec 8a, 2026-10-21) and intervals in the aggregation (Aggregation_Spec 2)."""
import numpy as np

from hyparena.aspid import IndicatorSpec, aggregate, cardinal_range, expected_value
from hyparena.card import lifespan
from hyparena.card.models import HypothesisCard
from tests.test_card_rules import load



def _card(age, strain="unknown", sex="unknown", name="ex5_resveratrol_endpoint"):
    card = HypothesisCard.model_validate(load(name)["card"])
    card.pico.population.age_at_start, card.pico.population.strain, card.pico.population.sex = age, strain, sex
    return card


def test_age_parsing():
    assert lifespan.age_days("600 days") == 600
    assert lifespan.age_days("20 months") == 20 * 30.44
    assert lifespan.age_days("20-month-old mice") == 20 * 30.44
    assert lifespan.age_days("18-20 months") == 19 * 30.44
    assert lifespan.age_days("65 years") == 65 * 365.25
    assert lifespan.age_days("middle age") is None


def test_median_lookup_rule():
    assert lifespan.median_interval("mouse", "UM-HET3", "female") == (887, 887)
    assert lifespan.median_interval("mouse", "UM-HET3") == (803, 887)              # sex unknown: both sexes
    assert lifespan.median_interval("mouse") == (803, 901)                         # strain unknown: all strains
    assert lifespan.median_interval("mouse", "BALB/c") is None                     # strain not in the table
    assert lifespan.median_interval("fly", "", "male") is None                     # only Dahomey females
    assert lifespan.median_interval("fly") == (63, 70)
    assert lifespan.median_interval("human")[0] == 83.9 * 365.25                   # the "both" row, high-income
    assert lifespan.median_interval("human", population="older adults in a middle-income country")[0] == 79.5 * 365.25


def test_values_of_data_sources_19():
    """The fractions printed in Data_Sources 19.2 come out of the tables."""
    assert lifespan.late_start(_card("middle age")) == (0.3378, 0.5686)            # 0.34-0.57
    assert lifespan.late_start(_card("old")) == (0.6081, 0.9098)                   # 0.61-0.91
    assert lifespan.late_start(_card("old", "UM-HET3", "female")) == (0.6177, 0.8236)   # 0.62-0.82
    assert lifespan.late_start(_card("very old")) == (0.8108, 1.0)
    assert lifespan.late_start(_card("late middle age")) == (0.3378, 0.9098)       # JAX gap: union
    assert lifespan.late_start(_card("600 days", "UM-HET3", "female")) == round(600 / 887, 4)
    assert lifespan.late_start(_card("1200 days", "UM-HET3", "female")) == 1.0     # capped
    human = _card("older adults, healthy", name="ex1_rapamycin_healthspan")
    assert lifespan.late_start(human) == (0.7747, 1.0)                             # >= 65 years / 83.9
    assert lifespan.late_start(_card("young")) is None                             # not in the table
    assert lifespan.late_start(_card("unknown")) is None


def test_middle_aged_is_not_read_as_aged():
    assert lifespan.verbal_age_days("mouse", "middle-aged") == (10 * 30.44, 15 * 30.44)
    assert lifespan.verbal_age_days("human", "older adults") == (65 * 365.25, None)
    assert lifespan.verbal_age_days("worm", "old") is None


def test_interval_is_drawn_within_its_bounds():
    spec = IndicatorSpec("late_start", "cardinal", bounds=(0.0, 1.0))
    assert cardinal_range(spec, (0.4, 0.6)) == (0.4, 0.6) and cardinal_range(spec, None) == (0.0, 1.0)
    assert expected_value(spec, (0.4, 0.6)) == (0.5, True)
    res = aggregate({"a": {"late_start": (0.4, 0.6)}, "b": {"late_start": 0.5}, "c": {"late_start": None}},
                    [spec], None, K=4000, seed=1)
    assert 0.4 <= res.quantiles["a"][0] and res.quantiles["a"][2] <= 0.6
    assert res.std["b"] < 1e-12 and res.std["c"] > res.std["a"] > 0.01                # interval narrows the spread
    assert abs(res.expected["a"] - 0.5) < 0.01

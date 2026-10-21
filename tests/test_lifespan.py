"""late_start (card spec 8a, 2026-10-21) and intervals in the aggregation (Aggregation_Spec 2)."""
import numpy as np

from hyparena.aspid import IndicatorSpec, aggregate, cardinal_range, expected_value
from hyparena.card import lifespan
from hyparena.card.models import HypothesisCard
from tests.test_card_rules import load

TABLE = {"medians": [{"species": "mouse", "median_days": 800},
                     {"species": "mouse", "strain": "UM-HET3", "sex": "female", "median_days": 900},
                     {"species": "mouse", "strain": "UM-HET3", "median_days": 850}],
         "verbal_ages": {"mouse": [{"terms": ["middle age", "middle-aged"], "fraction": [0.4, 0.6]}]}}


def test_age_parsing():
    assert lifespan.age_days("600 days") == 600
    assert lifespan.age_days("20 months") == 20 * 30.44
    assert lifespan.age_days("20-month-old mice") == 20 * 30.44
    assert lifespan.age_days("18-20 months") == 19 * 30.44
    assert lifespan.age_days("65 years") == 65 * 365.25
    assert lifespan.age_days("middle age") is None


def test_median_lookup_most_specific_first():
    assert lifespan.median_days("mouse", "UM-HET3", "female", TABLE) == 900
    assert lifespan.median_days("mouse", "UM-HET3", "male", TABLE) == 850
    assert lifespan.median_days("mouse", "C57BL/6J", "", TABLE) == 800
    assert lifespan.median_days("worm", "", "", TABLE) is None


def _card(age, strain="unknown", sex="unknown"):
    card = HypothesisCard.model_validate(load("ex5_resveratrol_endpoint")["card"])
    card.pico.population.age_at_start, card.pico.population.strain, card.pico.population.sex = age, strain, sex
    return card


def test_late_start_number_interval_unknown():
    assert lifespan.late_start(_card("400 days"), TABLE) == 0.5
    assert lifespan.late_start(_card("900 days", "UM-HET3", "female"), TABLE) == 1.0
    assert lifespan.late_start(_card("1200 days"), TABLE) == 1.0                 # capped
    assert lifespan.late_start(_card("middle age"), TABLE) == (0.4, 0.6)
    assert lifespan.late_start(_card("old"), TABLE) is None                       # not in the table: unknown
    assert lifespan.late_start(_card("unknown"), TABLE) is None
    assert lifespan.late_start(_card("400 days"), {"medians": [], "verbal_ages": {}}) is None


def test_interval_is_drawn_within_its_bounds():
    spec = IndicatorSpec("late_start", "cardinal", bounds=(0.0, 1.0))
    assert cardinal_range(spec, (0.4, 0.6)) == (0.4, 0.6) and cardinal_range(spec, None) == (0.0, 1.0)
    assert expected_value(spec, (0.4, 0.6)) == (0.5, True)
    res = aggregate({"a": {"late_start": (0.4, 0.6)}, "b": {"late_start": 0.5}, "c": {"late_start": None}},
                    [spec], None, K=4000, seed=1)
    assert 0.4 <= res.quantiles["a"][0] and res.quantiles["a"][2] <= 0.6
    assert res.std["b"] < 1e-12 and res.std["c"] > res.std["a"] > 0.01                # interval narrows the spread
    assert abs(res.expected["a"] - 0.5) < 0.01

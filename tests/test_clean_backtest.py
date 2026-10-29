import json

import pytest

from hyparena.card.models import HypothesisCard
from scripts import clean_backtest as cb

POOL = "data/backtest/outcomes_2024-12-31.json"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    from hyparena.tools import compounds
    monkeypatch.setattr(compounds, "lookup", lambda name: None)


def test_every_pool_sentence_becomes_a_valid_card_from_its_text_only():
    hyps = json.load(open(POOL))["hypotheses"]
    cards = cb.cards(POOL)
    assert len(cards) == len(hyps) == 33
    for h, c in zip(hyps, cards):
        card = HypothesisCard.model_validate(c)
        out = card.outcome_claim
        assert out.source_span == h["title"] and out.relation == "extends_lifespan_in"
        assert out.subject.label.lower() in h["title"].lower()


def test_the_card_carries_start_age_dose_and_species_of_the_text():
    t = json.load(open("data/validation/l1_10_pool.json"))["items"][0]["card"]
    mouse = cb.card("Dietary epicatechin (started at 7 months) extends the median lifespan of genetically heterogeneous "
                    "UM-HET3 mice of at least one sex.", 1, t)
    assert mouse["claims"][0]["qualifiers"]["age_at_start"] == "7 months" and mouse["claims"][0]["object"]["label"] == "mouse"
    combo = cb.card("Dietary atorvastatin + telmisartan extends the median lifespan of genetically heterogeneous UM-HET3 mice "
                    "of at least one sex.", 2, t)
    assert [i["label"] for i in combo["pico"]["intervention"]] == ["atorvastatin", "telmisartan"]
    worm = cb.card("Meclizine (at higher doses) extends the lifespan of Caenorhabditis nematodes across genetically diverse "
                   "species and strains.", 3, t)
    q = worm["claims"][0]["qualifiers"]
    assert q["species"] == "Caenorhabditis elegans" and q["dose"] == "higher doses" and worm["pico"]["population"]["taxon"] == "NCBITaxon:6239"
    with pytest.raises(ValueError):
        cb.card("Rapamycin is good.", 4, t)


def test_probes_cover_the_other_species_only():
    t = json.load(open("data/validation/l1_10_pool.json"))["items"][0]["card"]
    worm = HypothesisCard.model_validate(cb.card("Fisetin extends the lifespan of Caenorhabditis nematodes across genetically "
                                                 "diverse species and strains.", 1, t))
    assert [p.object.label for p in cb.species_probes(worm)] == ["mouse", "Drosophila melanogaster"]


def test_the_spec_fixes_units_and_the_policy_before_the_run():
    from hyparena import prespec
    s = prespec.load("specs/clean-2024-12-31.yaml")
    assert s["as_of"] == "2024-12-31" and s["policy"]["models"] == "none" and s["L3.3"]["dropped_indicators"] == ["late_start"]
    assert "per regimen" in s["units"]["L3.3"] and "per compound" in s["units"]["L3.9"] and s["expectations_before_run"]


def test_negative_groups_never_reuse_an_excluded_finding():
    from hyparena.negatives import select
    rows = []
    for c in ("A", "B"):                                   # two findings with two significant increases each
        rows += [{"compound_name": c, "species": "worm", "avg_lifespan_significance": "S", "avg_lifespan_change_percent": "10",
                  "pubmed_id": f"{c}{i}"} for i in range(2)]
    rows += [{"compound_name": f"N{i}", "species": "worm", "avg_lifespan_significance": "NS", "avg_lifespan_change_percent": "1",
              "pubmed_id": f"n{i}"} for i in range(10)]
    assert {g["positive"]["compound"] for g in select(rows, 5, 10)} == {"A", "B"}
    assert [g["positive"]["compound"] for g in select(rows, 5, 10, exclude=frozenset({("A", "worm")}))] == ["B"]

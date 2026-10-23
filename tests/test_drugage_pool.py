"""The free DrugAge calibration pool: strata by depth of evidence, cards by template and valid under the card rules."""
from pathlib import Path

import yaml

from hyparena.card.models import HypothesisCard
from hyparena.card.rules import validate_card
from scripts import drugage_pool as dp


def test_strata_follow_the_depth_of_evidence_at_t():
    assert dp._stratum(2, 5) == "deep" and dp._stratum(1, 0) == "shallow"
    assert dp._stratum(0, 1) == "other_species" and dp._stratum(0, 0) == "none"


def test_a_card_by_template_is_valid_and_carries_the_strain():
    d = yaml.safe_load((Path(__file__).parent / "fixtures" / "cards" / "ex3_rapamycin_mechanism.yaml").read_text(encoding="utf-8"))
    template = HypothesisCard.model_validate(d["card"]).model_dump(by_alias=True)
    h = {"id": "cal001", "compound": "Metformin", "strain": "UM-HET3", "stratum": "deep", "text": dp.TEXT.format(c="Metformin", strain="UM-HET3")}
    card = HypothesisCard.model_validate(dp._card(h, template, 7))
    assert card.id == "H-0007" and card.raw_id == "cal001" and card.pico.population.strain == "UM-HET3"
    assert len(card.claims) == 1 and card.claims[0].source_span in h["text"]
    assert validate_card(card, h["text"]) == []


def test_the_committed_pool_has_every_stratum_and_no_labels():
    import json
    pool = json.loads(Path("data/calibration/drugage_2015.json").read_text())
    by = {}
    for h in pool["hypotheses"]:
        by.setdefault(h["stratum"], []).append(h)
        assert "label" not in h and h["text"] == dp.TEXT.format(c=h["compound"], strain=h["strain"])
    assert set(by) == set(dp.STRATA) and all(len(v) == 10 for v in by.values())
    assert all(h["first_date"] > pool["source"]["as_of"] for h in by["none"])
    assert all(h["mouse_papers_by_T"] >= 2 for h in by["deep"]) and all(h["mouse_papers_by_T"] == 1 for h in by["shallow"])

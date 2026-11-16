"""Admission: an interventional hypothesis with its outcome written as a claim is admitted without an endpoint class."""
import json
from pathlib import Path

import pytest

from hyparena.card.models import HypothesisCard
from hyparena.scoring.rules import admit

CARDS = Path(__file__).resolve().parents[2] / "longevity-kg" / "reviews" / "argon-2026-11-13" / "bench_card_v2_ours_v17.json"


def _card(**outcome):
    from hyparena.card.models import Claim, Entity
    card = HypothesisCard.model_validate({
        "id": "t", "raw_id": "t", "hypothesis_type": "interventional", "claim_plain": "x",
        "pico": {"population": {"taxon": "NCBITaxon:10090", "label": "mice"}, "intervention": [{"type": "compound", "label": "x"}],
                 "outcome": {"endpoint": "unknown", "metric": outcome.get("metric", "unknown"), "direction": "improve"}},
        "claims": []})
    if outcome.get("claim"):
        card.claims.append(Claim(id="c1", subject=Entity(label="x"), relation="promotes", object=Entity(label="epithelial regeneration"),
                                 source_span="x", link="outcome", role="outcome"))
    return card


def test_an_outcome_claim_or_a_named_measure_is_an_outcome():
    assert admit(_card(claim=True)).decision == "accepted"
    assert admit(_card(metric="epithelial regeneration")).decision == "accepted"
    a = admit(_card())
    assert a.decision == "needs_refinement" and a.missing_critical == ["pico.outcome.endpoint"]


@pytest.mark.skipif(not CARDS.exists(), reason="the private data repository is not checked out")
def test_the_written_hypotheses_of_pack_26_are_admitted():
    cards = json.loads(CARDS.read_text())
    for cid in ("N03", "N15", "N22", "N25", "P20", "P43", "P50", "P53"):
        assert admit(HypothesisCard.model_validate(cards[cid]["card"])).decision == "accepted", cid

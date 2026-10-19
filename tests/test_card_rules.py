"""Card rules against the worked examples of the card specification (tests/fixtures/cards)."""
from pathlib import Path

import pytest
import yaml

from hyparena.card.models import HypothesisCard, Verification, json_schema
from hyparena.card.rules import admit, claim_status, evidence_profile, finalize, validate_card

FIX = Path(__file__).parent / "fixtures" / "cards"
EXAMPLES = ["ex1_rapamycin_healthspan", "ex2_senolytics_function", "ex3_rapamycin_mechanism", "ex5_resveratrol_endpoint"]


def load(name):
    return yaml.safe_load((FIX / f"{name}.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", EXAMPLES)
def test_declared_card_is_valid(name):
    d = load(name)
    card = HypothesisCard.model_validate(d["card"])
    assert validate_card(card, d["raw"]) == []
    assert admit(card).decision == d["expected"]["admission"]


@pytest.mark.parametrize("name", EXAMPLES)
def test_statuses_and_profile(name):
    d = load(name)
    card = HypothesisCard.model_validate(d["card"])
    ver = finalize(card, Verification.model_validate(d["verification"]))
    by_id = {c.id: c for c in card.claims}
    got = {cv.id: cv.status for cv in ver.claims}
    assert got == d["expected"]["statuses"]
    prof = ver.evidence_profile.model_dump()
    for key, value in d["expected"]["profile"].items():
        assert prof[key] == value, (key, prof[key], value)
    assert ver.known_result == d["expected"]["known_result"]


def test_endpoint_mismatch_is_not_support():
    d = load("ex5_resveratrol_endpoint")
    card = HypothesisCard.model_validate(d["card"])
    ver = Verification.model_validate(d["verification"])
    cv = ver.claims[0]
    cv.counterevidence = []                      # only the healthspan sentence left: still not support
    assert claim_status(cv, card.claims[0]) == "unverified"


def test_source_span_must_be_verbatim():
    d = load("ex1_rapamycin_healthspan")
    card = HypothesisCard.model_validate(d["card"])
    card.claims[0].source_span = "by blocking mTORC1"
    assert any("source_span" in p for p in validate_card(card, d["raw"]))


def test_one_outcome_claim():
    d = load("ex1_rapamycin_healthspan")
    card = HypothesisCard.model_validate(d["card"])
    card.claims[3].role = "mechanism"
    assert any("outcome" in p for p in validate_card(card))


@pytest.mark.parametrize("case", load("ex4_admission")["cases"], ids=lambda c: c["name"])
def test_admission_and_known_result(case):
    card = HypothesisCard.model_validate(case["card"])
    adm = admit(card)
    exp = case["expected"]
    assert adm.decision == exp["decision"]
    if "missing" in exp:
        assert adm.missing_critical == exp["missing"]
    if "context_specificity" in exp:
        assert adm.context_specificity == exp["context_specificity"]
    if "known_result" in exp:
        ver = finalize(card, Verification.model_validate(case["verification"]))
        assert ver.known_result is exp["known_result"]


def test_json_schema_exports():
    s = json_schema()
    assert "HypothesisCard" in s and "properties" in s["HypothesisCard"]

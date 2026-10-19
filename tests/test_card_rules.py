"""Card rules against the worked examples of the card specification (tests/fixtures/cards)."""
from pathlib import Path

import pytest
import yaml

from hyparena.card.models import HypothesisCard, Verification, json_schema
from hyparena.card.rules import (admit, claim_status, contrast_status, evidence_profile, finalize, validate_card,
                                 verified_layer_problems)

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
    for cid, contrast in d["expected"].get("contrast", {}).items():
        assert next(cv for cv in ver.claims if cv.id == cid).contrast == contrast
    assert verified_layer_problems(card, ver) == []


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


@pytest.mark.parametrize("x,y,expected", [
    ("refuted", "refuted", ("refuted", [])), ("supported", "supported", ("refuted", [])),
    ("unverified", "supported", ("refuted", [])), ("supported", "contested", ("contested", [])),
    ("supported", "refuted", ("supported", [])), ("contested", "refuted", ("contested", [])),
    ("supported", "unverified", ("unverified", ["contrast_unchecked"])),
    ("supported", "unresolved", ("unverified", ["contrast_unchecked"])),
    ("contested", "unverified", ("contested", [])), ("unverified", "unverified", ("unverified", []))])
def test_contrast_rule_table(x, y, expected):
    assert contrast_status(x, y) == expected


def _contrast_case():
    d = load("ex3_rapamycin_mechanism")
    card = HypothesisCard.model_validate(d["card"])
    ver = Verification.model_validate(d["verification"])
    x = next(cv for cv in ver.claims if cv.id == "c2")
    x.evidence[0].quote_role = "finding"         # pretend X were supported
    return card, ver


def test_contrast_supported_y_refutes_supported_x():
    card, ver = _contrast_case()
    ver = finalize(card, ver)
    assert {cv.id: cv.status for cv in ver.claims}["c2"] == "refuted"
    assert ver.evidence_profile.gate == "filtered"


def test_contrast_unchecked_y_gives_no_support_for_free():
    card, ver = _contrast_case()
    ver.claims = [cv for cv in ver.claims if cv.id != "a1"]
    ver = finalize(card, ver)
    c2 = next(cv for cv in ver.claims if cv.id == "c2")
    assert c2.status == "unverified" and "contrast_unchecked" in c2.flags
    assert ver.evidence_profile.gate == "pass"
    assert c2.evidence                           # evidence for X stays attached


def test_contrast_y_in_another_species_does_not_decide():
    card, ver = _contrast_case()
    card.declared_alternatives[0].qualifiers["species"] = "C. elegans"
    ver = finalize(card, ver)
    c2 = next(cv for cv in ver.claims if cv.id == "c2")
    assert c2.contrast["y_status"] == "unverified" and c2.status == "unverified"


def test_contrast_needs_rejected_alternative():
    d = load("ex3_rapamycin_mechanism")
    card = HypothesisCard.model_validate(d["card"])
    card.declared_alternatives[0].stated_as = "listed"
    problems = validate_card(card, d["raw"])
    assert any("contrast" in p for p in problems)
    card = HypothesisCard.model_validate(d["card"])
    card.claims[1].qualifiers.pop("contrast")
    assert any("rejected alternative" in p for p in validate_card(card, d["raw"]))


def test_alternative_span_must_be_verbatim():
    d = load("ex3_rapamycin_mechanism")
    card = HypothesisCard.model_validate(d["card"])
    card.declared_alternatives[0].source_span = "not by slowing ageing"
    assert any(p.startswith("a1: source_span") for p in validate_card(card, d["raw"]))


def test_inheritance_rules():
    d = load("ex2_senolytics_function")
    card = HypothesisCard.model_validate(d["card"])
    assert validate_card(card, d["raw"]) == []
    c3 = card.claims[2]                          # general mechanism claim: subject is not the intervention
    c3.inherited_from_pico = ["species"]
    c3.qualifiers["species"] = "human"
    assert any("c3" in p and "intervention" in p for p in validate_card(card, d["raw"]))
    card = HypothesisCard.model_validate(d["card"])
    card.claims[0].qualifiers["species"] = "mouse"   # inherited value differs from PICO
    assert any("c1: inherited species" in p for p in validate_card(card, d["raw"]))
    card = HypothesisCard.model_validate(d["card"])
    card.claims[0].inherited_from_pico = ["tissue"]
    assert any("cannot be inherited" in p for p in validate_card(card, d["raw"]))


def test_plain_string_alternatives_are_listed_and_not_checked():
    d = load("ex1_rapamycin_healthspan")
    card = HypothesisCard.model_validate({**d["card"], "declared_alternatives": ["food intake"]})
    assert card.declared_alternatives[0].stated_as == "listed" and card.rejected_alternatives == []
    assert validate_card(card, d["raw"]) == []


def test_ex_vivo_does_not_support_an_organism_claim():
    d = load("ex2_senolytics_function")
    card = HypothesisCard.model_validate(d["card"])
    ver = Verification.model_validate(d["verification"])
    cv = ver.claims[0]
    cv.evidence[0].qualifiers_match = {"species": "yes"}     # the verifier did not mark the context: the rule still holds
    assert claim_status(cv, card.claims[0]) == "unverified"
    claim = card.claims[0].model_copy(update={"qualifiers": {}, "inherited_from_pico": []})
    assert claim_status(cv, claim) == "supported"            # no organism stated: cell evidence counts (rung cells)


def test_unmarked_inheritance_is_marked_or_rejected():
    from hyparena.card.rules import mark_inherited
    d = load("ex2_senolytics_function")
    card = HypothesisCard.model_validate(d["card"])
    card.claims[0].inherited_from_pico = []          # species human copied without the mark
    assert any("c1: species" in p for p in validate_card(card, d["raw"]))
    assert validate_card(mark_inherited(card), d["raw"]) == [] and card.claims[0].inherited_from_pico == ["species"]
    card.claims[2].qualifiers["species"] = "human"   # general mechanism claim: cannot inherit → a problem stays
    assert any("c3: species" in p for p in validate_card(mark_inherited(card), d["raw"]))

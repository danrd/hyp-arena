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
    prof = ver.evidence_profile.model_dump(by_alias=True)
    for key, value in d["expected"]["profile"].items():
        assert prof[key] == value, (key, prof[key], value)
    assert ver.known_result == d["expected"]["known_result"]
    if "alternatives" in d["expected"]:
        assert [{"id": a.id, "source": a.source, "status": a.status} for a in ver.alternatives] == d["expected"]["alternatives"]
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
    """Synthetic (spec 7, 2026-10-21): Example 3 without Neff 2013, so Y is supported, and X pretended supported."""
    d = load("ex3_rapamycin_mechanism")
    card = HypothesisCard.model_validate(d["card"])
    ver = Verification.model_validate(d["verification"])
    next(cv for cv in ver.claims if cv.id == "a1").counterevidence = []
    x = next(cv for cv in ver.claims if cv.id == "c2")
    x.evidence[0].quote_role = "finding"         # pretend X were supported
    return card, ver


def test_contrast_supported_y_refutes_supported_x():
    card, ver = _contrast_case()
    ver = finalize(card, ver)
    assert {cv.id: cv.status for cv in ver.claims}["c2"] == "refuted"
    assert ver.evidence_profile.gate == "filtered"
    assert ver.evidence_profile.gate_reason == "contrast rule: a1 supported (PMID:22587563)"


def test_contrast_split_y_makes_the_outcome_contested():
    d = load("ex3_rapamycin_mechanism")
    card = HypothesisCard.model_validate(d["card"])
    ver = finalize(card, Verification.model_validate(d["verification"]))
    c2 = next(cv for cv in ver.claims if cv.id == "c2")
    assert c2.status == "contested" and c2.contrast["y_status"] == "contested"
    assert ver.evidence_profile.gate == "pass"


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


def test_listed_alternative_span_must_be_verbatim():
    d = load("ex1_rapamycin_healthspan")
    alt = {"id": "a1", "subject": {"label": "rapamycin"}, "relation": "suppresses", "object": {"label": "food intake"},
           "source_span": "by lowering food intake", "stated_as": "listed"}
    card = HypothesisCard.model_validate({**d["card"], "declared_alternatives": [alt]})
    assert any(p.startswith("a1: source_span") for p in validate_card(card, d["raw"]))


def test_refined_variant_specificity():
    d = load("ex2_senolytics_function")                # R-0004b has the text and card of Example 2
    assert admit(HypothesisCard.model_validate(d["card"])).context_specificity == 3


# ---- inheritance from PICO (spec 9): species and strain only, only claims about the intervention ----

def _ex2():
    d = load("ex2_senolytics_function")
    return d, HypothesisCard.model_validate(d["card"])


def test_inheritance_is_mandatory_and_deterministic():
    from hyparena.card.rules import mark_inherited
    d, card = _ex2()
    for c in card.claims[:2]:
        c.qualifiers.pop("species"), c.inherited_from_pico.clear()
    assert any("c1: species must be inherited" in p for p in validate_card(card, d["raw"]))
    card = mark_inherited(card)
    assert [c.inherited_from_pico for c in card.claims] == [["species"], ["species"], [], []]
    assert card.claims[0].qualifiers["species"] == "human" and validate_card(card, d["raw"]) == []


def test_span_naming_the_organism_blocks_inheritance():
    from hyparena.card.rules import mark_inherited
    d = load("ex1_rapamycin_healthspan")
    card = HypothesisCard.model_validate(d["card"])
    c3 = card.claims[2]                              # "in mice where it extends lifespan": named, not inherited
    c3.inherited_from_pico = ["species"]
    assert mark_inherited(card).claims[2].inherited_from_pico == []


def test_molecular_relations_never_inherit():
    from hyparena.card.rules import mark_inherited
    d = load("ex1_rapamycin_healthspan")
    card = HypothesisCard.model_validate(d["card"])
    c1 = card.claims[0]                              # rapamycin inhibits mTORC1: molecular
    assert mark_inherited(card).claims[0].inherited_from_pico == [] and "species" not in c1.qualifiers
    c1.qualifiers["species"], c1.inherited_from_pico = "human", ["species"]
    assert any(p.startswith("c1:") for p in validate_card(card, d["raw"]))


def test_organism_relation_inherits_into_the_object():
    from hyparena.card.rules import mark_inherited
    d = load("ex1_rapamycin_healthspan")
    card = HypothesisCard.model_validate(d["card"])
    c2 = card.claims[1]                              # the pre-2026-10-19 normalizer output
    c2.object.label, c2.object.id = "multiple aspects of aging", None
    c2.qualifiers, c2.inherited_from_pico = {}, []
    c2 = mark_inherited(card).claims[1]
    assert (c2.object.label, c2.qualifiers.get("species"), c2.qualifiers.get("measure")) == \
        ("human", "human", "multiple aspects of aging")
    assert c2.inherited_from_pico == ["species"] and validate_card(card, d["raw"]) == []


def test_only_species_and_strain_inherit():
    from hyparena.card.rules import mark_inherited
    d, card = _ex2()
    card.claims[0].inherited_from_pico = ["species", "age_at_start"]
    assert any("cannot be inherited" in p for p in validate_card(card, d["raw"]))
    assert mark_inherited(card).claims[0].inherited_from_pico == ["species"]


# ---- human rungs and the subgroup rule (spec 8) ----

def test_human_claim_has_a_status_per_rung():
    d = load("ex1_rapamycin_healthspan")
    card = HypothesisCard.model_validate(d["card"])
    ver = finalize(card, Verification.model_validate(d["verification"]))
    c4 = next(cv for cv in ver.claims if cv.id == "c4")
    assert c4.rung_status == {"human_markers": "contested", "human_clinical": "contested"}


def test_whole_sample_support_on_one_rung_is_not_contested_by_another():
    d = load("ex1_rapamycin_healthspan")
    card = HypothesisCard.model_validate(d["card"])
    ver = Verification.model_validate(d["verification"])
    c4 = next(cv for cv in ver.claims if cv.id == "c4")
    c4.evidence[0].flags = []                        # pretend the support were in the whole sample
    c4.evidence[0].human_rungs = ["human_clinical"]
    ver = finalize(card, ver)
    c4 = next(cv for cv in ver.claims if cv.id == "c4")
    assert c4.rung_status == {"human_markers": "refuted", "human_clinical": "supported"}
    assert ver.evidence_profile.effect_level == "human_clinical"


def test_record_rungs_fall_back_to_the_endpoint():
    from hyparena.card.models import EvidenceRecord
    from hyparena.card.rules import record_rungs
    rec = lambda **k: EvidenceRecord(source="PubMed", record_id="PMID:1", epistemic_type="A_text", **k)
    assert record_rungs(rec(endpoint="biomarker")) == ["human_markers"]
    assert record_rungs(rec(endpoint="lifespan")) == ["human_clinical"]
    assert record_rungs(rec(endpoint="biomarker", human_rungs=["human_clinical"])) == ["human_clinical"]


# ---- strain rule (spec 7) ----

def _strain_case(strain, inherited=False):
    d = load("ex5_resveratrol_endpoint")
    card = HypothesisCard.model_validate(d["card"])
    if inherited:
        card.pico.population.strain = strain
        card.claims[0].source_span = "Resveratrol started in middle age extends the lifespan"
        card.claims[0].qualifiers["species"] = "mouse"
        card.claims[0].inherited_from_pico = ["species", "strain"]
    card.claims[0].qualifiers["strain"] = strain
    ver = Verification.model_validate(d["verification"])
    for r in ver.claims[0].counterevidence:
        r.strain = "UM-HET3" if r.program else "C57BL/6"
    return card, ver


def test_strain_unspecified_in_the_card_is_na():
    from hyparena.card.rules import add_strain_analogs
    d = load("ex5_resveratrol_endpoint")
    card = HypothesisCard.model_validate(d["card"])
    ver = Verification.model_validate(d["verification"])
    ver.claims[0].counterevidence[0].strain = "C57BL/6"
    ver = add_strain_analogs(card, ver)
    assert ver.claims[0].counterevidence[0].qualifiers_match["strain"] == "n/a" and len(ver.claims) == 1


def test_other_strain_moves_to_an_analog():
    from hyparena.card.rules import add_strain_analogs
    card, ver = _strain_case("C57BL/6")
    ver = add_strain_analogs(card, ver)
    c1, an1 = ver.claims[0], ver.claims[-1]
    assert [r.record_id for r in c1.counterevidence] == ["PMID:18599363"]
    assert c1.counterevidence[0].qualifiers_match["strain"] == "yes"
    assert an1.id == "an1" and an1.claim.role == "analog" and "strain" not in an1.claim.qualifiers
    assert [r.record_id for r in an1.counterevidence] == ["PMID:20974732"]
    assert not c1.refusals[1:]                      # stated strain: no inherited_mismatch
    ver = finalize(card, ver)
    assert {cv.id: cv.status for cv in ver.claims} == {"c1": "refuted", "an1": "refuted"}


def test_inherited_strain_that_differs_leaves_a_refusal():
    from hyparena.card.rules import add_strain_analogs
    card, ver = _strain_case("C57BL/6", inherited=True)
    ver = add_strain_analogs(card, ver)
    assert any(r.type == "inherited_mismatch" and r.record_id == "PMID:20974732" for r in ver.claims[0].refusals)
    assert ver.claims[-1].id == "an1"


def test_analog_strain_does_not_make_a_known_result():
    from hyparena.card.models import EvidenceRecord
    from hyparena.card.rules import add_strain_analogs
    card, ver = _strain_case("C57BL/6")
    cv = ver.claims[0]
    cv.counterevidence = []
    cv.evidence = [EvidenceRecord(source="PubMed", record_id="PMID:2", epistemic_type="A_text", species="mouse",
                                  endpoint="lifespan", quote_role="finding", strain="DBA/2", quote="x",
                                  qualifiers_match={"species": "yes", "age_at_start": "yes", "intervention_match": "exact"})]
    ver = finalize(card, add_strain_analogs(card, ver))
    assert ver.evidence_profile.effect_level == "mammals" and ver.known_result is False


def test_generic_heterogeneous_strain_matches_um_het3():
    from hyparena.card.models import EvidenceRecord
    from hyparena.card.rules import strain_match
    d = load("ex5_resveratrol_endpoint")
    claim = HypothesisCard.model_validate(d["card"]).claims[0]
    claim.qualifiers["strain"] = "genetically heterogeneous"
    rec = EvidenceRecord(source="PubMed", record_id="PMID:1", epistemic_type="A_text", strain="UM-HET3")
    assert strain_match(claim, rec) == "yes"
    rec.strain = ""
    assert strain_match(claim, rec) is None


def test_stage1_findings():
    """Normalizer outputs seen on real models (2026-10-21): an inherited species written as the population label,
    and a mechanistic parse of "Senescent cells are bad for health" with an `other` outcome."""
    from hyparena.card.rules import mark_inherited
    d = load("ex1_rapamycin_healthspan")
    card = HypothesisCard.model_validate(d["card"])
    card.pico.population.label = "healthy older adults"
    card.claims[1].qualifiers["species"] = "healthy older adults"
    assert mark_inherited(card).claims[1].qualifiers["species"] == "human"
    r5 = HypothesisCard.model_validate({
        "id": "H-5", "raw_id": "R-0005", "hypothesis_type": "mechanistic", "claim_plain": "x",
        "pico": {"population": {"label": "unknown"}, "intervention": [], "outcome": {"endpoint": "unknown"}},
        "claims": [{"id": "c1", "subject": {"label": "senescent cells"}, "relation": "other", "note": "bad for",
                    "object": {"label": "health"}, "role": "outcome", "source_span": "Senescent cells are bad for health."}]})
    assert admit(r5).decision == "not_a_hypothesis"


def test_gate_reason_of_a_curated_record_is_its_pmid():
    from hyparena.card.models import EvidenceRecord
    d = load("ex5_resveratrol_endpoint")
    card = HypothesisCard.model_validate(d["card"])
    ver = Verification.model_validate(d["verification"])
    ver.claims[0].counterevidence = [EvidenceRecord(
        source="DrugAge", record_id="DrugAge:Resveratrol/Mus musculus/PMID20974732", epistemic_type="B_curated",
        linked_pmid="20974732", species="mouse", endpoint="lifespan", quote_role="finding", program={"name": "ITP"},
        qualifiers_match={"species": "yes", "intervention_match": "exact"})]
    assert finalize(card, ver).evidence_profile.gate_reason == "PMID:20974732"

"""Context rule for disease models (2026-10-22): for a claim about lifespan, health or ageing a record from a disease
model does not give or take away the status unless the claim is about that disease; it becomes an analog
an<N> of type disease_model with a refusal `population_mismatch`, stays out of the effect level, and feeds the
alternatives. The label needs a disease name and the place where it is named; a bare flag counts for nothing."""
from pathlib import Path

import pytest
import yaml

from hyparena.card import contexts
from hyparena.card.alternatives import rows
from hyparena.card.models import EvidenceRecord, HypothesisCard, Verification
from hyparena.card.rules import add_disease_analogs, finalize, is_disease_analog

FIX = Path(__file__).parent / "fixtures" / "cards"


def rec(rid, effect, disease="", model="disease_model", evidence="the abstract names the model", **kw):
    r = EvidenceRecord(source="PubMed", record_id=rid, epistemic_type="A_text", species="mouse", endpoint="lifespan",
                       quote_role="finding", effect=effect, qualifiers_match={"intervention_match": "exact"}, **kw)
    if disease:
        r.model_type, r.disease, r.disease_evidence = model, disease, evidence
        r.flags.append("disease_model")
    return r


def case(support, against, disease=None, population=None, restored=frozenset()):
    d = yaml.safe_load((FIX / "ex5_resveratrol_endpoint.yaml").read_text(encoding="utf-8"))
    card = HypothesisCard.model_validate(d["card"])
    if disease:
        card.claims[0].qualifiers["disease"] = disease
    if population:
        card.pico.population.label = population
    ver = Verification.model_validate(d["verification"])
    cv = ver.claims[0]
    cv.evidence, cv.counterevidence, cv.refusals = support, against, []
    ver = finalize(card, add_disease_analogs(card, ver, restored))
    return card, ver


MINOCYCLINE = [rec("PMID:1", "increase", "ALS"), rec("PMID:2", "increase", "ALS"),
               rec("PMID:3", "increase", "congenital muscular dystrophy"),
               rec("PMID:4", "increase", "autoimmune lymphoproliferative disease")]
MINOCYCLINE_AGAINST = [rec("PMID:5", "no_effect", "ALS")]


def test_a_records_of_als_and_dystrophy_models_do_not_set_the_status_of_a_claim_about_ordinary_mice():
    card, ver = case([r.model_copy(deep=True) for r in MINOCYCLINE], [r.model_copy(deep=True) for r in MINOCYCLINE_AGAINST])
    main, analog = ver.claims[0], ver.claims[-1]
    assert main.status == "unverified" and not main.evidence and not main.counterevidence
    assert [x.type for x in main.refusals] == ["population_mismatch"] * 5
    assert analog.id == "an1" and analog.claim.role == "analog" and is_disease_analog(analog.claim)
    assert len(analog.evidence) == 4 and len(analog.counterevidence) == 1
    assert ver.evidence_profile.effect_level == "none" and ver.evidence_profile.disease_models == 5
    assert "disease models" not in ver.evidence_profile.effect_level_note
    assert any(a.type == "disease_specific" and "records from disease models: 5" in a.explanation for a in rows(card, ver))


def test_b_the_same_claim_about_mice_with_als_counts_the_als_records():
    card, ver = case([r.model_copy(deep=True) for r in MINOCYCLINE], [r.model_copy(deep=True) for r in MINOCYCLINE_AGAINST],
                     disease="ALS")
    main = ver.claims[0]
    assert {r.disease for r in main.evidence + main.counterevidence} == {"ALS"}
    assert main.status == "contested"                              # two ALS records for, one against
    assert {x.record_id for x in main.refusals} == {"PMID:3", "PMID:4"}   # another disease is a mismatch


def test_b2_a_population_that_names_the_disease_is_enough():
    _, ver = case([rec("PMID:1", "increase", "amyotrophic lateral sclerosis")], [], population="mice with ALS")
    assert ver.claims[0].status == "supported" and len(ver.claims) == 1


def test_c_a_record_without_a_disease_name_or_a_place_does_not_take_the_status():
    nameless = rec("PMID:1", "increase")
    nameless.flags.append("disease_model")                         # a bare flag, as an extractor may write it
    no_place = rec("PMID:2", "increase", "ALS", evidence="")
    _, ver = case([nameless], [])
    assert ver.claims[0].status == "supported" and len(ver.claims) == 1
    _, ver = case([no_place], [])
    assert ver.claims[0].status == "supported" and not ver.claims[0].refusals


def test_d_a_claim_about_healthy_mice_with_a_record_on_healthy_mice_works_as_before():
    _, ver = case([rec("PMID:1", "increase")], [])
    assert ver.claims[0].status == "supported" and ver.evidence_profile.effect_level == "mammals"
    assert ver.evidence_profile.disease_models == 0


def test_ageing_models_are_not_counted_yet():
    _, ver = case([rec("PMID:1", "increase", "progeria model", model="aging_model")], [])
    assert ver.claims[0].status == "unverified" and ver.evidence_profile.aging_models == 1
    assert ver.evidence_profile.effect_level == "none" and ver.evidence_profile.disease_models == 0


def test_an_expert_can_restore_a_record():
    _, ver = case([rec("PMID:1", "increase", "ALS")], [], restored=frozenset({"PMID:1"}))
    assert ver.claims[0].status == "supported" and not ver.claims[0].refusals


def test_the_step_can_be_applied_again_with_the_same_result():
    card, ver = case([r.model_copy(deep=True) for r in MINOCYCLINE], [r.model_copy(deep=True) for r in MINOCYCLINE_AGAINST])
    again = finalize(card, add_disease_analogs(card, ver.model_copy(deep=True)))
    assert [cv.id for cv in again.claims] == [cv.id for cv in ver.claims]
    assert len(again.claims[-1].evidence) == 4 and len(again.claims[0].refusals) == 5


def test_other_kinds_of_claims_are_not_touched():
    d = yaml.safe_load((FIX / "ex5_resveratrol_endpoint.yaml").read_text(encoding="utf-8"))
    card = HypothesisCard.model_validate(d["card"])
    card.claims[0].relation = "changes_biomarker"
    ver = Verification.model_validate(d["verification"])
    ver.claims[0].evidence = [rec("PMID:1", "increase", "ALS")]
    ver = add_disease_analogs(card, ver)
    assert len(ver.claims[0].evidence) == 1 and len(ver.claims) == 1


def test_the_table_names_a_disease_and_where_it_is_named():
    r = EvidenceRecord(source="PubMed", record_id="PMID:1")
    contexts.flag(r, "Methods. Mice expressing mutant SOD1(G37R) were treated with the drug. They lived longer.")
    assert r.model_type == "disease_model" and r.disease == "ALS" and "SOD1(G37R)" in r.disease_evidence
    s = EvidenceRecord(source="DrugAge", record_id="DrugAge:x")
    contexts.flag(s, strain="laminin-alpha2-null")
    assert s.disease == "congenital muscular dystrophy" and s.disease_evidence.startswith("curated strain")
    p = EvidenceRecord(source="PubMed", record_id="PMID:2")
    contexts.flag(p, "Progeroid mice of the Ercc1-deficient line lived longer.")
    assert p.model_type == "aging_model" and "aging_model" in p.flags

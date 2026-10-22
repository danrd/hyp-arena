"""Claim scope over the sexes and the protocol strata (2026-10-22): `sex_scope: any` makes an effect in one sex
enough and a null result in the other sex not "against"; without the scope the same records give `contested`
with the flag `sex_conflict`; sex in ITP and CITP is a stratum fixed in advance, not a post hoc subgroup."""
from pathlib import Path

import pytest
import yaml

from hyparena.card import indicators as ind
from hyparena.card.alternatives import rows
from hyparena.card.models import EvidenceRecord, HypothesisCard, ProgramInfo, Verification
from hyparena.card.rules import (finalize, mark_strata, set_sex_scope, sex_scope_from_text, statuses,
                                 subgroup_only)
from hyparena.card.verifier import mark_subgroup

FIX = Path(__file__).parent / "fixtures" / "cards"


def rec(rid, sex, effect, **kw):
    return EvidenceRecord(source="PubMed", record_id=rid, epistemic_type="A_text", species="mouse", endpoint="lifespan",
                          quote_role="finding", sex=sex, effect=effect, qualifiers_match={"intervention_match": "exact"}, **kw)


def case(scope, support, against):
    d = yaml.safe_load((FIX / "ex5_resveratrol_endpoint.yaml").read_text(encoding="utf-8"))
    card = HypothesisCard.model_validate(d["card"])
    card.claims[0].sex_scope = scope
    ver = Verification.model_validate(d["verification"])
    cv = ver.claims[0]
    cv.evidence, cv.counterevidence, cv.refusals = support, against, []
    ver = finalize(card, ver)
    return card, ver, ver.claims[0]


def test_a_scope_any_effect_in_males_and_null_in_females_is_supported():
    card, ver, cv = case("any", [rec("PMID:1", "male", "increase")], [rec("PMID:2", "female", "no_effect")])
    assert cv.status == "supported" and "other_sex_null" in cv.flags and "sex_conflict" not in cv.flags
    assert [r.record_id for r in cv.counterevidence] == ["PMID:2"]                  # the null result is kept in the card
    assert ind.compute(card, ver, {})["both_sexes"] == "one"                          # and counts in both_sexes
    assert any(a.type == "sex_specific" for a in rows(card, ver))                    # and in the alternative


def test_b_the_same_records_without_the_scope_are_contested_with_sex_conflict():
    _, _, cv = case("unspecified", [rec("PMID:1", "male", "increase")], [rec("PMID:2", "female", "no_effect")])
    assert cv.status == "contested" and "sex_conflict" in cv.flags and "other_sex_null" not in cv.flags


def test_c_scope_any_harm_in_the_other_sex_is_still_contested():
    _, _, cv = case("any", [rec("PMID:1", "male", "increase")], [rec("PMID:2", "female", "decrease")])
    assert cv.status == "contested"


def test_scope_any_null_in_the_same_sex_is_a_real_conflict():
    _, _, cv = case("any", [rec("PMID:1", "male", "increase")], [rec("PMID:2", "male", "no_effect")])
    assert cv.status == "contested"


def test_scope_any_nulls_in_both_sexes_refute_and_one_null_alone_does_not():
    _, _, both = case("any", [], [rec("PMID:2", "male", "no_effect"), rec("PMID:3", "female", "no_effect")])
    assert both.status == "refuted"
    _, _, one = case("any", [], [rec("PMID:2", "female", "no_effect")])
    assert one.status == "unverified"
    _, _, whole = case("any", [rec("PMID:1", "male", "increase")], [rec("PMID:2", "both", "no_effect")])
    assert whole.status == "contested"                                              # a null in the whole sample counts


def test_d_a_post_hoc_subgroup_stays_subgroup_only():
    sub = rec("PMID:1", "female", "increase", flags=["subgroup_only"])
    assert subgroup_only([sub])
    _, _, cv = case("unspecified", [sub], [])
    assert cv.status == "unverified" and "subgroup_unchecked" in cv.flags
    _, _, cv = case("unspecified", [sub], [rec("PMID:2", "both", "no_effect")])
    assert cv.status == "contested"


def itp_records():
    curated = EvidenceRecord(source="DrugAge", record_id="DrugAge:X/PMID1", epistemic_type="B_curated", linked_pmid="1",
                             species="mouse", endpoint="lifespan", sex="male", effect="increase",
                             program=ProgramInfo(name="ITP"), qualifiers_match={"intervention_match": "exact"})
    return curated, rec("PMID:1", "male", "increase"), rec("PMID:1", "male", "increase")


def test_sex_in_an_itp_paper_is_a_prespecified_stratum_not_a_subgroup():
    curated, pubmed, _ = itp_records()
    null_f = rec("PMID:1", "female", "no_effect")
    mark_subgroup([curated, pubmed], [null_f])                  # one sex in a paper with a null for the other
    assert "sex" in pubmed.strata and "sex" in curated.strata and not subgroup_only([pubmed])
    plain = rec("PMID:9", "male", "increase")                   # the same pattern outside a protocol: a subgroup
    mark_subgroup([plain], [rec("PMID:9", "female", "no_effect")])
    assert "subgroup_only" in plain.flags and subgroup_only([plain])


def test_a_flag_set_by_code_before_the_stratum_was_known_is_removed():
    _, pubmed, _ = itp_records()
    mark_subgroup([pubmed], [rec("PMID:1", "female", "no_effect")])             # without the curated row: flagged
    assert "subgroup_only" in pubmed.flags
    curated, _, _ = itp_records()
    mark_strata([curated, pubmed])
    assert "subgroup_only" not in pubmed.flags and not subgroup_only([pubmed])


def test_unknown_sex_of_an_itp_paper_record_is_taken_from_its_curated_row():
    curated, _, _ = itp_records()
    curated.sex = "female"
    unknown = rec("PMID:1", "unknown", "no_effect")
    mark_strata([curated, unknown])
    assert unknown.sex == "female"


@pytest.mark.parametrize("text, scope", [
    ("Dietary X extends the median lifespan of UM-HET3 mice of at least one sex.", "any"),
    ("X extends lifespan in either sex of mice.", "any"),
    ("X extends lifespan in male mice.", "unspecified"),
    ("X extends lifespan in mice.", "unspecified")])
def test_sex_scope_comes_from_the_words_of_the_text(text, scope):
    assert sex_scope_from_text(text) == scope


def test_set_sex_scope_marks_the_outcome_claim_and_keeps_a_value_that_was_written():
    d = yaml.safe_load((FIX / "ex5_resveratrol_endpoint.yaml").read_text(encoding="utf-8"))
    card = HypothesisCard.model_validate(d["card"])
    set_sex_scope(card, "Resveratrol extends the lifespan of mice.")
    assert all(c.sex_scope == "unspecified" for c in card.claims)
    set_sex_scope(card, "Resveratrol extends the lifespan of mice of at least one sex.")
    assert card.outcome_claim.sex_scope == "any"


def test_reapplying_the_old_rules_reproduces_a_saved_run():
    import json
    from hyparena.card.pipeline import reapply_rules
    path = Path("runs/stage4/itp2010_test.json")
    if not path.exists():
        pytest.skip("the saved backtest runs are local (runs/ is not tracked)")
    old = json.loads(path.read_text())
    new = reapply_rules(old, new_rules=False)
    assert [x["outcome"] for x in old["items"]] == [x["outcome"] for x in new["items"]]
    assert json.loads(json.dumps([x["indicators"] for x in old["items"]])) == json.loads(json.dumps([x["indicators"] for x in new["items"]]))
    assert all(old["ranking"][p]["order"] == new["ranking"][p]["order"] for p in old["ranking"])

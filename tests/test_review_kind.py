from hyparena.card.models import Claim, EvidenceRecord
from hyparena.card import rules_v32 as r32
from hyparena.card.review_kind import certainty_factor, certainty_from_abstract, design_from_pubtypes


def test_design_follows_pubmed_publication_types():
    assert design_from_pubtypes("review", ["Journal Article", "Meta-Analysis"]) == ("meta_analysis", "systematic")
    assert design_from_pubtypes("review", ["Systematic Review"]) == ("review", "systematic")
    assert design_from_pubtypes("rct", ["Review"]) == ("review", "narrative")
    assert design_from_pubtypes("other", ["Randomized Controlled Trial"]) == ("rct", "")
    assert design_from_pubtypes("rct", ["Journal Article"]) == ("rct", "")


def test_grade_certainty_from_the_abstract_sets_the_meta_analysis_weight():
    assert certainty_from_abstract("Moderate certainty evidence showed that resistance exercise ...") == "moderate"
    assert certainty_from_abstract("very low quality of evidence (GRADE)") == "very_low"
    assert certainty_from_abstract("no grading here") == ""
    assert (certainty_factor("high"), certainty_factor("low"), certainty_factor("very_low"), certainty_factor("")) == (1.0, 0.5, 0.25, 0.75)


def _rec(**k):
    base = dict(source="PubMed", record_id="PMID:1", epistemic_type="A_text", study_type="review", lab_or_cohort="PMID:1",
                quote="q", quote_role="finding", species="human", design="meta_analysis", n_total=1000,
                comparison="between_groups", effect_reported="SMD = 0.9", effect_class="large")
    base.update(k)
    return EvidenceRecord(**base)


def test_a_meta_analysis_weighs_by_its_certainty_on_the_outcome_link():
    claim = Claim(id="c1", subject={"label": "x"}, relation="improves_healthspan_in", object={"label": "human"},
                  qualifiers={"species": "human"}, role="outcome", link="outcome", source_span="x")
    w_mod = r32.record_weight_v36(_rec(certainty="moderate"), claim, False)
    w_none = r32.record_weight_v36(_rec(certainty=""), claim, False)
    w_low = r32.record_weight_v36(_rec(certainty="low"), claim, False)
    assert w_mod > w_none > w_low and abs(w_none / w_mod - 0.75) < 1e-9
    with r32.method():                                   # the current rules (v3.6 and later), as the reports use them
        f = r32.weight_factors(_rec(certainty="low"), claim, False)
    assert f["design"] == ["meta_analysis (low)", 0.5]

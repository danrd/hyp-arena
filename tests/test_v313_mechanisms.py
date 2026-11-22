"""Unit tests for v3.13 mechanisms: paper_outcomes/v2 and Channel B implementation_readiness/v1."""
from types import SimpleNamespace

from hyparena import METHOD_VERSION
from hyparena.card.models import ClaimVerification, Intervention
from hyparena.novelty import novelty_v34 as nv
from hyparena.reading import implementation as impl
from hyparena.reading import paper_outcomes as po
from hyparena.scoring import v3_extra as vx
from tests.test_rules_v3 import card, claim, rec


def test_method_version_is_v313():
    assert METHOD_VERSION == "v3.13"


def test_paper_outcomes_validate_and_novelty_demotion():
    paper = {
        "title": "High-voltage pulsed electrical stimulation in chronic ulcers",
        "abstract": "The reduction in the wound area at 4 weeks was 28.6% greater than sham.",
    }
    raw = {
        "paper_outcomes": [
            {
                "source_pmid": "36011679",
                "intervention_tested": "pulsed electrical stimulation",
                "same_intervention_family": "class_or_regimen",
                "endpoint_role": "human_clinical_or_function",
                "same_outcome_domain": "same",
                "species": "human",
                "measure": "reduction in the wound area",
                "excerpt": "The reduction in the wound area at 4 weeks was 28.6% greater than sham.",
            },
            {
                "source_pmid": "36011679",
                "intervention_tested": "knockout",
                "same_intervention_family": "different",
                "endpoint_role": "animal_behavioral_or_function",
                "same_outcome_domain": "same",
                "species": "animal",
                "measure": "wound area",
                "excerpt": "Fabricated quote not in abstract.",
            },
        ]
    }
    rows, issues = po.validate(raw, "36011679", paper)
    assert len(rows) == 1 and issues == ["unverified_excerpt"]

    # Wire into novelty_v34: empty outcome + supported earlier step would be new_combination, demoted to analog
    c = card([
        claim("c1", "adaptive ES", "promotes", "keratinocyte migration", "step"),
        claim("c2", "adaptive ES", "improves_healthspan_in", "human", "outcome", "outcome"),
    ])
    cvs = [ClaimVerification(id="c1", evidence=[rec(1, "animal", n=40, effect="large")])]
    assert nv.novelty(c, cvs) == "new_combination"
    assert nv.novelty(c, cvs, paper_outcomes=rows) == "analog"
    assert nv.novelty_source(c, cvs, paper_outcomes=rows) == "36011679"

    # Non-qualifying (physiological marker or different intervention) must NOT demote
    non_qual = [{**rows[0], "endpoint_role": "physiological_or_marker"}]
    assert nv.novelty(c, cvs, paper_outcomes=non_qual) == "new_combination"
    diff_int = [{**rows[0], "same_intervention_family": "different"}]
    assert nv.novelty(c, cvs, paper_outcomes=diff_int) == "new_combination"


def test_channel_b_implementation_validation_and_v3_extra_integration():
    supplied = {
        "37578890": {
            "title": "Peptide S293 restores Cx36 coupling in human islets",
            "abstract": "Application of S293 to perifused human islets restored coordinated Ca2+ oscillations.",
        }
    }
    good = impl.validate({
        "limiting_means": "S293 peptide in human islets",
        "limiting_operation": "perifused human islet stimulation",
        "implementation_status": "conditional",
        "evidence_pmid": "37578890",
        "evidence_quote": "Application of S293 to perifused human islets restored coordinated Ca2+ oscillations.",
        "gap": "Not tested in vivo.",
    }, supplied)
    assert good["verified_status"] == "conditional" and good["quote_ok"] is True

    # Unverified quote MUST downgrade automatically to missing
    bad = impl.validate({
        "limiting_means": "optogenetic KCR in 3D cartilage",
        "limiting_operation": "viral transduction",
        "implementation_status": "demonstrated",
        "evidence_pmid": "37578890",
        "evidence_quote": "Non-existent quote.",
        "gap": "",
    }, supplied)
    assert bad["verified_status"] == "missing" and bad["quote_ok"] is False and bad["issue"] == "unverified_quote"

    # Wire into v3_extra for non-compound intervention
    c = card([claim("c2", "tACS", "improves_healthspan_in", "human", "outcome", "outcome")])
    c.pico.intervention = [Intervention(type="device", label="phase-locked slow-wave tACS")]
    c.decisive_experiment.system, c.decisive_experiment.duration_class, c.decisive_experiment.n_planned = "human", "months", 80
    assert impl.is_non_drug(c) is True
    assert vx.readiness_assessment(c) == (None, "implementation_unverified")
    assert vx.readiness_assessment(c, implementation=good) == (0.5, "impl_conditional")
    assert vx.readiness_assessment(c, implementation=bad) == (0.0, "impl_missing")
    fb = vx.feasibility_breakdown(c, implementation=good)
    assert fb["score"] == vx.feasibility(c, implementation=good) == round((0 + 2 / 3 + 2 / 3 + 0.5) / 4, 3)
    rp = next(p for p in fb["parts"] if p["key"] == "readiness")
    assert rp["reason"] == "impl_conditional" and rp["evidence_pmid"] == "37578890"

"""Reader v18 (specs/reading/class-findings-2026-11-15.yaml): the three answers per abstract checked against the finding,
the outcome match, the effect numbers and the standardised difference code computes from them."""
import pytest

from hyparena.card.models import EvidenceRecord
from hyparena.reading import effect_class as ec
from hyparena.reading import verifier as vf
from hyparena.scoring import rules_v32 as r32

ABS = {"1": {"title": "Balance training in older adults", "abstract":
             "Sixty participants were randomised. SPPB improved by 0.86 points (95% CI 0.32 to 1.41) over control. "
             "Gait speed was 1.10 ± 0.20 m/s after training and 0.98 ± 0.22 m/s in controls (p < 0.01)."}}


def _reply(paper, records=()):
    return {"papers": [{"pmid": "1", **paper}], "records": list(records)}


def _rec(**k):
    return {"pmid": "1", "quote": "SPPB improved by 0.86 points (95% CI 0.32 to 1.41) over control.", "stance": "supports", **k}


def test_a_fitting_abstract_called_none_goes_back_to_the_reader():
    v = _reply({"intervention": "same_kind", "outcome": "narrower", "own_result": "yes", "finding": "none"})
    assert any("rule 1d" in p for p in vf.paper_problems(v, ABS))
    assert vf.paper_problems(v, ABS, own_part_only=True) == []          # a competing explanation may still say none


def test_a_finding_needs_three_fitting_answers_and_a_record():
    ok = {"intervention": "component", "outcome": "same", "own_result": "yes", "finding": "for"}
    assert vf.paper_problems(_reply(ok, [_rec()]), ABS) == []
    assert any("no record" in p for p in vf.paper_problems(_reply(ok), ABS))
    wide = {**ok, "outcome": "broader"}
    assert any('it is "none"' in p for p in vf.paper_problems(_reply(wide, [_rec()]), ABS))
    assert vf.paper_problems(_reply({"intervention": "other", "outcome": "other", "own_result": "no", "finding": "none"}), ABS) == []


def test_every_abstract_needs_an_entry_and_closed_values():
    assert any("no entry" in p for p in vf.paper_problems({"papers": [], "records": []}, ABS))
    bad = _reply({"intervention": "class", "outcome": "same", "own_result": "yes", "finding": "for"}, [_rec()])
    assert any("needs intervention" in p for p in vf.paper_problems(bad, ABS))


def test_numbers_not_in_the_abstract_are_dropped():
    src = ABS["1"]["title"] + " " + ABS["1"]["abstract"]
    got = ec.clean_numbers({"difference": "0.86", "ci_low": "0.32", "ci_high": "1.41", "p": "<0.01", "smd": "0.5",
                            "unit": "points"}, src)
    assert got == {"difference": "0.86", "ci_low": "0.32", "ci_high": "1.41", "p": "<0.01", "unit": "points"}
    assert ec.clean_numbers({"difference": "86"}, src) == {}             # "86" is not "0.86"


def test_d_from_numbers_by_kind():
    assert ec.d_from_numbers({"smd": "-0.45"}, None, "between_groups") == (0.45, "smd")
    d, kind = ec.d_from_numbers({"ratio": "0.5"}, None, "between_groups")
    assert kind == "ratio" and d == pytest.approx(0.382, abs=0.001)
    d, kind = ec.d_from_numbers({"difference": "0.86", "ci_low": "0.32", "ci_high": "1.41"}, 188, "between_groups")
    assert kind == "interval" and d == pytest.approx(0.45, abs=0.01)
    d, kind = ec.d_from_numbers({"intervention": "1.10", "control": "0.98", "sd_intervention": "0.20", "sd_control": "0.22"},
                                60, "between_groups")
    assert kind == "means" and d == pytest.approx(0.57, abs=0.01)
    assert ec.d_from_numbers({"difference": "0.86"}, 188, "between_groups") == (None, "")
    assert ec.d_from_numbers({"p": "<0.01"}, 60, "between_groups") == (None, "")


def test_fields_reach_the_record_and_only_the_named_kinds_reach_the_weight():
    src = ABS["1"]["title"] + " " + ABS["1"]["abstract"]
    rec = EvidenceRecord(source="PubMed", record_id="PMID:1", quote="q", n_total=60, comparison="between_groups",
                         qualifiers_match={"intervention_match": "exact"})
    vf.v18_fields(rec, {"outcome_match": "narrower", "outcome_measure": "Gait speed", "effect_numbers": {
        "intervention": "1.10", "control": "0.98", "sd_intervention": "0.20", "sd_control": "0.22"}},
        {"intervention": "component", "outcome": "narrower"}, src)
    assert (rec.outcome_match, rec.outcome_measure, rec.effect_d_kind) == ("narrower", "Gait speed", "means")
    assert rec.qualifiers_match["intervention_match"] == "class"        # one part of a combined intervention
    assert r32.effect_weight(rec, False) == 0.5                         # "means" is on the record, not in the weight
    rec.effect_d, rec.effect_d_kind = 0.6, "interval"
    assert r32.effect_weight(rec, False) >= r32.EFFECT_FULL_FROM
    vf.v18_fields(rec, {"outcome_measure": "frailty index"}, {}, src)
    assert rec.outcome_measure == ""                                    # not the abstract's words


def test_the_template_renders_with_the_three_answers():
    from hyparena.card.llm import render
    from hyparena.card.models import Claim, Entity
    claim = Claim(id="c1", subject=Entity(label="squat exercise"), relation="promotes", object=Entity(label="physical performance"),
                  source_span="x", link="outcome")
    text = render("verify_claim", "v18", claim=claim, claim_plain="h", population="older adults", intervention="squats",
                  comparator="usual care", qualifiers="", alternative=False, competitor=False, contrast="", negated=False,
                  endpoint="", human_healthspan=False, history_text="", abstracts=[{"pmid": "1", "year": "2020", "title": "t", "abstract": "a", "review": False}])
    for needle in ("1c. ONE PART OF A COMBINED INTERVENTION", "1d. DECIDE THREE THINGS", '"own_result": "yes | no"',
                   '"effect_numbers": {}', "outcome_match"):
        assert needle in text

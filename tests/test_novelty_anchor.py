"""2026-10-23: novelty needs an anchor in the graph, and the multi-site program is a condition of robustness."""
from pathlib import Path

import yaml

from hyparena.card import indicators as ind
from hyparena.card.models import HypothesisCard, Verification
from hyparena.card.rules import finalize

FIX = Path(__file__).parent / "fixtures" / "cards"


def load(name):
    d = yaml.safe_load((FIX / f"{name}.yaml").read_text(encoding="utf-8"))
    return HypothesisCard.model_validate(d["card"]), Verification.model_validate(d["verification"])


def test_no_literature_gives_no_novelty_and_a_flag():
    card, ver = load("ex3_rapamycin_mechanism")
    assert ind.novelty(card, finalize(card, ver.model_copy(deep=True))) == "new_link"          # a mechanistic anchor
    for cv in ver.claims:
        cv.evidence, cv.counterevidence = [], []
    ver = finalize(card, ver)
    assert ver.evidence_profile.no_literature
    assert ind.novelty(card, ver) is None
    assert ind.compute(card, ver)["novelty"] is None                                          # unknown, drawn uniformly


def test_a_new_link_needs_a_supported_mechanism():
    card, ver = load("ex5_resveratrol_endpoint")                                              # literature, mechanism unverified
    ver = finalize(card, ver)
    assert not ver.evidence_profile.no_literature and ver.evidence_profile.mechanism == "unverified"
    assert ind.novelty(card, ver) is None


def test_the_other_novelty_levels_do_not_need_the_mechanism():
    card, ver = load("ex1_rapamycin_healthspan")                                              # translation, mechanism unverified
    ver = finalize(card, ver)
    assert ver.evidence_profile.mechanism == "unverified" and ind.novelty(card, ver) == "translation"


def test_the_indicator_set_has_no_multi_site_positive_but_keeps_the_flag():
    assert "multi_site_positive" not in {s.id for s in ind.INDICATORS} and "multi_site_positive" in ind.ALL_BY_ID
    card, ver = load("ex1_rapamycin_healthspan")
    ver = finalize(card, ver)
    assert ver.evidence_profile.multi_site_program["outcome"] == "positive" and ver.evidence_profile.robustness == "replicated"
    assert "multi_site_positive" not in ind.compute(card, ver)


def test_a_positive_program_makes_a_single_record_replicated():
    card, ver = load("ex1_rapamycin_healthspan")
    for cv in ver.claims:                                   # one supporting record, from the program, with one site
        cv.evidence = [r for r in cv.evidence if r.program][:1]
        for r in cv.evidence:
            r.program.sites_with_effect = 1
        cv.counterevidence = []
    ver = finalize(card, ver)
    assert ver.evidence_profile.multi_site_program.get("outcome") == "positive"
    assert ver.evidence_profile.robustness == "replicated"


def test_saved_runs_are_read_with_their_own_indicator_set():
    old = [{"id": "robustness"}, {"id": "multi_site_positive"}, {"id": "novelty"}]
    assert [s.id for s in ind.for_meta({"indicators": old})] == ["robustness", "multi_site_positive", "novelty"]
    assert [s.id for s in ind.for_meta({})] == [s.id for s in ind.INDICATORS]


def test_the_set_hash_changes_with_the_set_and_with_the_profiles():
    from hyparena.aspid import load_profiles
    a = ind.set_hash(ind.INDICATORS, load_profiles())
    assert a == ind.set_hash(list(ind.INDICATORS), load_profiles())
    assert a != ind.set_hash(ind.INDICATORS_V1, load_profiles()) and a != ind.set_hash(ind.INDICATORS)

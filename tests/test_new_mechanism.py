"""v3.9 (user decision 2026-11-11): the novelty level 'new mechanism of a known effect' — the outcome was already studied,
but a link between two supported neighbours has fewer than 5 PubMed records on its own subject and object before T."""
import pytest

from hyparena.card import aspid_v3
from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v3 as r3
from hyparena.card.models import ClaimVerification
from tests.test_analyze import _case, rec


@pytest.fixture(autouse=True)
def _no_approval(monkeypatch):
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)


def test_the_level_sits_between_analog_and_new_combination():
    assert nv.LEVELS == ("new_context", "translation", "analog", "new_mechanism", "new_combination", "new_link")
    assert aspid_v3.SPECS["N"].levels == nv.LEVELS


def test_a_new_link_between_supported_neighbours_counts_only_with_a_count_under_the_threshold():
    c, cvs, _ = _case()            # c1 supported (two animal studies), c2 without records, c3 outcome with an RCT
    assert [x.id for x in nv.mechanism_candidates(c, cvs)] == ["c2"]
    assert nv.novelty(c, cvs) == "new_context"                       # no count: novelty by absence is not assumed
    assert nv.novelty(c, cvs, absence={"c2": 0}) == "new_mechanism"
    assert nv.novelty(c, cvs, absence={"c2": 4}) == "new_mechanism"
    assert nv.novelty(c, cvs, absence={"c2": 5}) == "new_context"    # 5 or more papers: the link is known
    assert nv.novelty(c, cvs, absence={"c2": None}) == "new_context"  # the count failed or the label was too long


def test_no_candidate_without_a_supported_neighbour_or_with_records_on_the_link():
    c, cvs, _ = _case()
    no_c1 = [v for v in cvs if v.id != "c1"]
    assert nv.mechanism_candidates(c, no_c1) == []
    assert nv.novelty(c, no_c1, absence={"c2": 0}) == "new_context"
    with_c2 = cvs + [ClaimVerification(id="c2", evidence=[rec(5, "animal", n=40)])]
    assert nv.mechanism_candidates(c, with_c2) == []


def test_without_outcome_records_the_ladder_is_unchanged():
    c, cvs, _ = _case()
    no_out = [v for v in cvs if v.id != "c3"]
    assert nv.novelty(c, no_out, absence={"c2": 0}) == "new_link"


def test_the_count_uses_the_link_subject_and_object_only():
    c, cvs, _ = _case()
    seen = []
    counts = nv.mechanism_absence(c, cvs, "2026-11-06", get=lambda p: seen.append(p) or 2)
    assert counts == {"c2": 2}
    assert seen[0]["term"] == "(AMPK) AND (senescent cells)" and seen[0]["maxdate"] == "2026/11/06"


def test_losing_the_new_mechanism_is_drift_to_the_known():
    c, cvs, _ = _case()
    child = [v for v in cvs] + [ClaimVerification(id="c2", evidence=[rec(6, "animal", n=40)])]   # the link became known
    d = nv.drift((c, cvs), (c, child), absence=({"c2": 0}, None))
    assert d["N"] == ["new_mechanism", "new_context"] and d["drift_to_known"]

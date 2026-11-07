"""Method v3.4 (specs/v34-frontier-2026-11-07.yaml): P as non-refutation, the species charged once, constant precision before the
outcome, novelty N, leverage and the evolution drift flag (hand-made drifted pairs and controls)."""
import pytest

from hyparena.card import novelty_v34 as nv
from hyparena.card import rules_v3 as r3
from hyparena.card import rules_v32 as r32
from hyparena.card.models import ClaimVerification as CV
from tests.test_rules_v3 import card, claim, rec


@pytest.fixture(autouse=True)
def no_lookups(monkeypatch):
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)


OUT = claim("c9", "x", "improves_healthspan_in", "human", "outcome", "outcome")


def mech_card():
    return card([claim("c1", "x", "activates", "y", "engagement"), claim("c2", "y", "promotes", "z", "effect"), OUT])


def test_first_evidence_no_longer_lowers_P_and_support_rises():
    c = mech_card()
    none = r32.evaluate(c, [], v34=True)
    first = r32.evaluate(c, [CV(id="c1", evidence=[rec(1, "cells")])], v34=True)
    v33a = r32.evaluate(c, [], fold=True, neutral_unverified=True)
    v33b = r32.evaluate(c, [CV(id="c1", evidence=[rec(1, "cells")])], fold=True, neutral_unverified=True)
    assert v33b.P < v33a.P                                                   # the v3.3 paradox
    assert first.P == none.P == 1.0 and first.support_share > none.support_share
    against = r32.evaluate(c, [CV(id="c1", counterevidence=[rec(2, "animal", n=40)])], v34=True)
    softened = r32.evaluate(c, [CV(id="c1", evidence=[rec(1, "animal", n=40)], counterevidence=[rec(2, "animal", n=40)])], v34=True)
    assert against.P < softened.P < 1.0 and against.P_lo == against.P_hi == against.P
    assert r32.non_refutation(0.6, 0) == 1.0


def test_species_charged_once_on_the_outcome_and_constant_precision_before_it():
    o = card([OUT]).claims[0]
    mouse = rec(1, "animal", n=40, qm={"species": "no"})
    assert r32.record_weight(mouse, o, False, True) == pytest.approx(r32.record_weight(mouse, o, False) * 3 / 2)
    both = rec(2, "animal", n=40, qm={"species": "no", "population": "no"})
    assert r32.record_weight(both, o, False, True) == pytest.approx(r32.record_weight(both, o, False))
    m = mech_card().claims[0]
    assert r32.record_weight(rec(3, "cells", n=None), m, False, True) == r32.record_weight(rec(4, "cells", n=10 ** 6), m, False, True)
    assert r32.record_weight(rec(3, "cells", n=None), m, False, True) == pytest.approx(r32.record_weight(rec(3, "cells"), m, False) * 2)


def test_novelty_ladder():
    c = mech_card()
    assert nv.novelty(c, [CV(id="c9", evidence=[rec(1, "rct", n=200, qm={"population": "no"})])]) == "new_context"
    assert nv.novelty(c, [CV(id="c9", evidence=[rec(1, "animal", n=40, qm={"species": "no"})])]) == "translation"
    assert nv.novelty(c, [CV(id="c9", evidence=[rec(1, "rct", n=200, qm={"intervention_match": "class"})])]) == "analog"
    assert nv.novelty(c, [CV(id="c9", counterevidence=[rec(1, "rct", n=200)])]) == "new_context"     # asked, answered no
    sup = [CV(id="c1", evidence=[rec(1, "animal", n=40, effect="large")] * 1), CV(id="c2", evidence=[rec(2, "animal", n=40, effect="large")])]
    assert nv.novelty(c, sup) == "new_combination"
    assert nv.novelty(c, sup[:1]) == "new_link"
    assert nv.novelty(c, []) is None                                          # absence of data is not novelty
    assert nv.novelty(card([OUT]), []) is None


def test_leverage_needs_a_supported_rest_of_the_chain():
    c = mech_card()
    strong = [rec(i, "animal", n=40, effect="large") for i in range(1, 4)]
    lev, _, bott = nv.leverage(c, [CV(id="c1", evidence=strong), CV(id="c2", evidence=strong)])
    assert lev > 0 and bott == "c9"
    assert nv.leverage(c, [])[0] == 0.0                                       # a chain of guesses has none
    assert nv.leverage(card([OUT]), [])[0] == 0.0                             # one link alone has none


# ---- the drift flag: hand-made drifted pairs must be flagged, controls must not

def pair_base():
    c = mech_card()
    cvs = [CV(id="c1", evidence=[rec(1, "animal", n=40, effect="large")])]   # c2 and the outcome: no data -> new_link
    return c, cvs


def test_drifted_pairs_are_flagged():
    c, cvs = pair_base()
    assert nv.novelty(c, cvs) == "new_link"
    # 1. an exact human trial is now on the outcome (narrowed to where the RCT is)
    d1 = nv.drift((c, cvs), (c, cvs + [CV(id="c9", evidence=[rec(5, "rct", n=300)])]))
    # 2. the intervention swapped for a studied related compound
    d2 = nv.drift((c, cvs), (c, cvs + [CV(id="c9", evidence=[rec(6, "rct", n=300, qm={"intervention_match": "related_compound"})])]))
    # 3. the new link removed: the child is the outcome alone with records in another species
    child3 = card([claim("c1", "x", "activates", "y", "engagement"), OUT])
    d3 = nv.drift((c, cvs), (child3, cvs))
    # 4. a kept link moves to a lower level
    d4 = nv.drift((c, cvs), (c, [CV(id="c1", evidence=[rec(1, "animal", n=40, effect="large")]),
                                 CV(id="c2", evidence=[rec(7, "rct", n=300)])]))
    for d in (d1, d2, d3, d4):
        assert d["drift_to_known"], d


def test_controls_are_not_flagged():
    c, cvs = pair_base()
    assert not nv.drift((c, cvs), (c, cvs))["drift_to_known"]                                     # identical
    more = [CV(id="c1", evidence=[rec(1, "animal", n=40, effect="large"), rec(8, "cells")])]
    assert not nv.drift((c, cvs), (c, more))["drift_to_known"]                                    # support added, same level
    longer = card([claim("c1", "x", "activates", "y", "engagement"), claim("c2", "y", "promotes", "z", "effect"),
                   claim("c3", "z", "suppresses", "w", "effect"), OUT])
    assert not nv.drift((c, cvs), (longer, cvs))["drift_to_known"]                                # a new link added

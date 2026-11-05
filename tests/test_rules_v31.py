"""Method v3.1 rules (method-v3.md section 12): each change against v3 on a synthetic case; v3 itself unchanged."""
from types import SimpleNamespace

import pytest

from hyparena.card import rules_v3 as r3
from hyparena.card.models import ClaimVerification
from tests.test_rules_v3 import card, claim, rec


@pytest.fixture(autouse=True)
def no_lookups(monkeypatch):
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)


def _cv(cid, *records, against=()):
    return ClaimVerification(id=cid, evidence=list(records), counterevidence=list(against))


def test_point1_preclinical_links_use_the_preclinical_design_scale():
    c = card([claim("c1", "x", "activates", "AMPK", "engagement"),
              claim("c2", "x", "improves_healthspan_in", "human", "outcome", "outcome")]).claims
    mouse = rec(1, "animal", qm={"species": "no"})
    assert r3.record_weight(mouse, c[0], False, "v3") == pytest.approx(2 / 7 * 1 / 4 * 3 / 4 * 1 * 2 / 3)
    assert r3.record_weight(mouse, c[0], False, "v3.1") == pytest.approx(1 * 1 / 4 * 3 / 4 * 1 * 2 / 3)   # species still costs
    assert r3.record_weight(mouse, c[1], False, "v3.1") == r3.record_weight(mouse, c[1], False, "v3")    # outcome: as before


def test_point3_conflicting_data_ranks_above_no_data():
    c = card([claim("c1", "x", "activates", "y", "pathway"), claim("c2", "x", "improves_healthspan_in", "human", "outcome", "outcome")])
    cvs = [_cv("c1", rec(1, "animal"), against=[rec(2, "animal")])]
    v3, v31 = r3.evaluate(c, cvs), r3.evaluate(c, cvs, variant="v3.1")
    assert v3.links["c1"] == v31.links["c1"] == "contested"
    none_ = r3.evaluate(c, [], variant="v3.1")
    assert v3.P < r3.evaluate(c, []).P                  # v3: contested below unverified
    assert v31.P > none_.P                              # v3.1: above


def test_point4_a_cascade_of_pathway_links_is_one_slot():
    three = [claim("c1", "x", "activates", "y", "engagement"), claim("c2", "y", "activates", "z", "pathway"),
             claim("c3", "z", "improves_healthspan_in", "human", "outcome", "outcome")]
    five = three[:2] + [claim("c2b", "z", "activates", "z2", "pathway"), claim("c2c", "z2", "activates", "z3", "pathway")] + three[2:]
    assert r3.evaluate(card(five), [], variant="v3.1").P == pytest.approx(r3.evaluate(card(three), [], variant="v3.1").P)
    assert r3.evaluate(card(five), []).P < r3.evaluate(card(three), []).P            # v3 unchanged


def test_point5_approval_needs_the_target_in_the_link(monkeypatch):
    import hyparena.card.entities as ent
    import hyparena.tools.compounds as cp
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: claim.link == "engagement")
    monkeypatch.setattr(ent, "subject_compounds", lambda label, card: [SimpleNamespace(max_phase=4, targets=["CHEMBL1"])])
    monkeypatch.setattr(cp, "target_names", lambda t: ["prostaglandin g/h synthase 2", "ptgs2", "cox-2"])
    out = lambda o: r3.evaluate(card([claim("c1", "celecoxib", "inhibits", o, "engagement"),
                                      claim("c2", "celecoxib", "improves_healthspan_in", "human", "outcome", "outcome")]),
                                [], variant="v3.1").links["c1"]
    assert out("COX-2 activity") == "moderate"
    assert out("Kv1.3 channels in chondrocytes") == "unverified"


def test_point6a_hallmark_scope_needs_a_moderate_link():
    c = card([claim("c1", "x", "suppresses", "senescent cells", "pathway", hallmark="cellular_senescence"),
              claim("c2", "x", "improves_healthspan_in", "human", "outcome", "outcome")])
    weak = [_cv("c1", rec(1, "cells", effect="small"))]
    assert r3.evaluate(c, weak).scope == "hallmark"
    assert r3.evaluate(c, weak, variant="v3.1").scope == "organ"
    strong = [_cv("c1", rec(1, "animal", n=40, effect="large"), rec(2, "animal", n=40, effect="large"))]
    assert r3.evaluate(c, strong, variant="v3.1").scope == "hallmark"


def test_point6b_weak_alternatives_no_longer_saturate_informativeness():
    base = [claim("c1", "x", "improves_healthspan_in", "human", "outcome", "outcome")]
    alts = [{"id": f"p{i}", "subject": {"label": "a"}, "relation": "other", "object": {"label": f"b{i}"}, "support_pmids": [str(i)],
             "on_positive": "eliminated", "on_negative": "unchanged"} for i in range(3)]
    av = {f"p{i}": _cv(f"p{i}", rec(i, "cells", effect="small")) for i in range(3)}
    assert r3.evaluate(card(base, alts), [], av).I == pytest.approx(1.0)
    assert r3.evaluate(card(base, alts), [], av, variant="v3.1").I == pytest.approx(1 / 3 + 2 / 3 * (3 * 1 / 3) / 1.5, abs=1e-3)


def test_point7_a_paper_pubmed_marks_retracted_weighs_nothing():
    c = card([claim("c1", "x", "improves_healthspan_in", "human", "outcome", "outcome")]).claims[0]
    r = rec(1, "rct", n=400)
    r.flags.append("retracted_pubmed")
    assert r3.record_weight(r, c, False, "v3") > 0 and r3.record_weight(r, c, False, "v3.1") == 0.0


def test_pubmed_is_retracted():
    from hyparena.tools import pubmed
    assert pubmed.is_retracted({"pubtypes": ["Journal Article", "Retracted Publication"]})
    assert pubmed.is_retracted({"pubtypes": ["Journal Article"], "retraction_in": ["38553637"]})
    assert not pubmed.is_retracted({"pubtypes": ["Journal Article"]})

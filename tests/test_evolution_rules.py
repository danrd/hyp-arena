"""Evolution rules (manual section 11) and the hypothesis / experiment decomposition, on a saved parent and hand-made versions."""
import json

import pytest

from hyparena.card import evolution_rules as er
from hyparena.card import rules_v3 as r3
from hyparena.card.evolve_v3 import parent_parts
from scripts.v34_check import PROS

RUN = PROS / "run_60.json"
pytestmark = pytest.mark.skipif(not RUN.exists(), reason="private runs not present")


def _parent():
    run = json.loads(RUN.read_text())
    for u, r in run.items():
        it = r["items"][0]
        if not it.get("card") or "v3" not in it:
            continue
        card, cvs, alts = parent_parts(it)
        e, sup = er._supported(card, cvs, alts)
        has_against = any(cv.counterevidence for cv in cvs)
        if sup and has_against:
            logs = {}
            for c in r.get("calls", []):
                if c.get("kind") == "search":
                    logs[c.get("claim")] = c.get("pmids", [])
            return card, cvs, alts, logs
    pytest.skip("no parent with a supported link and a record against")


def test_identical_version_breaks_nothing():
    card, cvs, alts, logs = _parent()
    out = er.check((card, cvs, logs), (card, cvs, logs), mode="tune", parent_alts=alts, child_alts=alts)
    assert out["violations"] == []


def test_changed_supported_link_is_a_violation_in_tune_not_in_free():
    card, cvs, alts, logs = _parent()
    _, sup = er._supported(card, cvs, alts)
    target = sup[0]
    claims = [c.model_copy(update={"object": c.object.model_copy(update={"label": c.object.label + " (rewritten)"})})
              if c.id == target.id else c for c in card.claims]
    child = card.model_copy(update={"claims": claims})
    tune = er.check((card, cvs, logs), (child, cvs, logs), mode="tune", parent_alts=alts, child_alts=alts)
    free = er.check((card, cvs, logs), (child, cvs, logs), mode="free", parent_alts=alts, child_alts=alts)
    assert 3 in tune["violations"] and 3 not in free["violations"]


def test_dropped_record_against_not_read_is_a_violation():
    card, cvs, alts, logs = _parent()
    child_cvs = [cv.model_copy(update={"counterevidence": []}) for cv in cvs]
    out = er.check((card, cvs, logs), (card, child_cvs, {}), mode="tune", parent_alts=alts, child_alts=alts)
    gone = [r for r in out["rules"] if r["rule"] == 1][0]["gone_against"]
    if not gone:
        pytest.skip("the parent's records against weigh 0")
    assert 1 in out["violations"] and all(g["reason"] == "not read in the version" for g in gone)


def test_decomposition_of_identical_axes_is_zero_and_parts_sum():
    card, cvs, alts, _ = _parent()
    from hyparena.card import improvements as imp
    e = imp.evaluate(card, cvs, alts)
    a = imp.axes(e, None, {"feasibility": 0.5, "N": "analog"})
    # unknown values are drawn per entry, so identical axes differ by Monte Carlo noise (about 0.002 at K = 500)
    assert all(abs(v[k]) <= 0.004 for v in er.decompose(a, a, K=500).values() for k in ("total", "hypothesis", "experiment"))
    b = (dict(a[0], I=min(1.0, a[0]["I"] + 0.5)), dict(a[1], N="new_link"))
    for v in er.decompose(a, b, K=500).values():
        assert abs(v["hypothesis"] + v["experiment"] - v["total"]) <= 0.004


def test_pubmed_count_built_from_the_two_labels_only():
    seen = {}
    n = er.pubmed_pair_count("HIIT", "BDNF", "2026-11-06", get=lambda p: seen.setdefault("term", p["term"]) and 136)
    assert n == 136 and seen["term"] == "(HIIT) AND (BDNF)"
    assert er.pubmed_pair_count("tumor progression cancer therapies hormonal dysregulation", "muscle", "2026-11-06",
                                get=lambda p: 0) is None


def test_experiment_cost():
    c = er.experiment_cost("A double-blind 2x2x2 factorial RCT with vastus lateralis biopsy and HD-sEMG")
    assert c["arms"] == 8 and "biopsy" in c["invasive_or_specialised"] and "hd-semg" in c["invasive_or_specialised"]
    assert er.experiment_cost("a three-arm trial")["arms"] == 3

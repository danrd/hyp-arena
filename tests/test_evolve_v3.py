import json

from hyparena.card import evolve_v3 as ev
from hyparena.card import rules_v3 as r3
from hyparena.llm.fake import FakeLLMClient
from hyparena.llm.providers import GuardedClient
from tests.test_analyze import _case


def test_proposal_applies_the_given_items_and_code_rejects_copies():
    client = GuardedClient(FakeLLMClient(0), rpm=0, max_calls=10)
    parent = "Title: x improves function in older adults.\n" + "Hypothesis: x activates AMPK and improves function. " * 6
    items = [{"id": "i1", "type": "experiment_alternatives", "what": ("ru", "rule out exercise"), "facts": []}]
    v = ev.propose(client, "google", parent, "x activates", items)
    assert v is not None and v["applied"] == ["i1"]
    assert ev.problems({"text": parent, "applied": ["i1"]}, parent, "x", {"i1"})          # a copy is rejected
    assert ev.problems({"text": "y " * 200, "applied": ["i1"]}, parent, "metformin", {"i1"})   # the intervention must stay


def test_compare_reports_indicator_and_score_changes(monkeypatch):
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    c, cvs, alts = _case()
    def item(card, cvs, alts):
        return {"card": card.model_dump(), "verification": {"claims": [x.model_dump() for x in cvs]},
                "v3_alternatives": {k: v.model_dump() for k, v in alts.items()}, "v3": {"headroom_I": 1.0}}
    parent = c.model_copy(deep=True)
    for a in parent.proposed_alternatives:
        a.on_positive = "unchanged"                       # the parent's experiment leaves the alternative standing
    out = ev.compare(item(parent, cvs, alts), item(c, cvs, alts), {}, {})
    assert out["indicators"]["I"][1] > out["indicators"]["I"][0]
    assert all(after >= before for before, after in out["score"].values())
    assert not out["links"]["added"] and not out["links"]["removed"]


def test_the_report_section_shows_the_pair(monkeypatch):
    from hyparena import report_html as rh
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    c, cvs, alts = _case()
    def item(card):
        return {"card": card.model_dump(), "verification": {"claims": [x.model_dump() for x in cvs]},
                "v3_alternatives": {k: v.model_dump() for k, v in alts.items()}, "v3": {"headroom_I": 1.0}}
    parent = c.model_copy(deep=True)
    parent.proposed_alternatives[0].on_positive = "unchanged"
    cmp_ = ev.compare(item(parent), item(c), {}, {})
    evo = {"U1": {"items": [{"id": "i1", "cls": "rewrite", "type": "experiment_alternatives", "what": ("ру", "en"), "facts": [],
                             "expected": {"indicators": {}, "score": {"evidence": [0.5, 0.6]}}}],
                  "applied": ["i1"], "changes": [{"item": "i1", "what_changed": "added a control arm"}], "child_text": "t", "compare": cmp_},
           "U2": {"items": [], "skipped": "no rewrite item"}}
    html = rh.render_evolution(evo, {"U1": {"title": "A trial"}}, ["evidence", "evolution", "funding"])
    assert "added a control arm" in html and "U2" in html and 'id="ev-U1"' in html

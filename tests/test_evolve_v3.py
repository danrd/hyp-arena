import json

from hyparena.evolution import evolve_v3 as ev
from hyparena.scoring import rules_v3 as r3
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
    from hyparena.reports import report_html as rh
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
    html = rh.render_evolution(evo, {"U1": {"title": "A trial"}}, ["evidence", "funding", "frontier"])
    assert "added a control arm" in html and "U2" in html and 'id="ev-U1"' in html


def test_tuning_and_free_modes_are_named_apart_and_free_marks_a_distant_child():
    client = GuardedClient(FakeLLMClient(0), rpm=0, max_calls=10)
    parent = "Title: x improves function in older adults.\n" + "Hypothesis: x activates AMPK and improves function. " * 6
    items = [{"id": "i1", "type": "experiment_alternatives", "what": ("ru", "rule out exercise"), "facts": []}]
    v = ev.propose(client, "google", parent, "x activates", items, novel=["x — activates — AMPK"], feedback="N analog -> new_context")
    assert v is not None
    f = ev.propose_free(client, "google", parent, items, "frontier", "analog", "2026-11-06")
    assert f is not None and f["cited_pmids"] == ["12345678"]
    assert ev.distance(parent, parent) == 0.0 and ev.distance(parent, "a completely different text about yeast " * 10) > ev.NEW_AFTER
    assert ev.MODES == ("tune", "profile", "free")
    from hyparena.reports import report_html as rh
    assert "доработанная" in rh.evo_chip({"parent": "U1", "evo_mode": "tune"})
    assert "свободная" in rh.evo_chip({"parent": "U1", "evo_mode": "free", "new_after": True}) and "U1" in rh.evo_chip(
        {"parent": "U1", "evo_mode": "free", "new_after": True})
    from hyparena.prompts import __name__ as _  # noqa: F401
    from hyparena.card.llm import render
    assert "TUNING" in render("evolve_v3", "v2", parent="p", items=[], novel=["n"], feedback="f", history_text="")
    assert "Mechanism: ... (only if" in render("evolve_v3", "v2", parent="p", items=[], novel=[], feedback="", history_text="")


def test_tuning_by_profile_takes_the_items_that_raise_that_profile_most():
    def item(i, cls, ev_score):
        return {"id": i, "cls": cls, "type": "experiment_alternatives", "what": ("ru", "en"), "facts": [],
                "expected": None if ev_score is None else {"score": ev_score}}
    items = [item("i1", "rewrite", {"funding": [0.4, 0.5], "evidence": [0.4, 0.41]}),
             item("i2", "rewrite", {"funding": [0.4, 0.45], "evidence": [0.4, 0.6]}),
             item("i3", "rewrite", {"funding": [0.4, 0.38], "evidence": [0.4, 0.4]}),
             item("i4", "rewrite", None),                                   # write_mechanism: not computable, not chosen
             item("i5", "research", {"funding": [0.4, 0.9]})]               # needs new data, not a new text
    assert [i["id"] for i in ev.items_for_profile(items, "funding")] == ["i1", "i2"]
    assert [i["id"] for i in ev.items_for_profile(items, "evidence")] == ["i2", "i1"]
    assert len(ev.items_for_profile(items * 3, "funding", k=3)) == 3


def test_prompts_of_the_three_modes():
    from hyparena.card.llm import render
    base = dict(parent="p", items=[], novel=[], feedback="", history_text="")
    tune = render("evolve_v3", "v3", **base, profile="", order="", frontier_target=False)
    prof = render("evolve_v3", "v3", **base, profile="funding", order="W > I", frontier_target=False)
    front = render("evolve_v3", "v3", **base, profile="frontier", order="N > B", frontier_target=True)
    assert "TUNING" in tune and "profile" not in tune.split("This is TUNING")[0]
    assert '"funding"' in prof and "W > I" in prof and "new_link" not in prof
    assert "exactly one new step" in front and '"new_link"' in front
    free = dict(parent="p", items=[], novelty="analog", as_of="2026-11-14", history_text="")
    assert "better research hypothesis overall" in render("evolve_free", "v2", **free, profile="", order="", novelty_first=False)
    assert '"frontier"' in render("evolve_free", "v2", **free, profile="frontier", order="N", novelty_first=True)


def test_free_evolution_without_a_profile_and_tuning_by_profile_on_the_fake_llm():
    client = GuardedClient(FakeLLMClient(0), rpm=0, max_calls=10)
    parent = "Title: x improves function in older adults.\n" + "Hypothesis: x activates AMPK and improves function. " * 6
    items = [{"id": "i1", "type": "experiment_alternatives", "what": ("ru", "rule out exercise"), "facts": []}]
    assert ev.propose_free(client, "google", parent, items, None, "analog", "2026-11-14") is not None
    v = ev.propose(client, "google", parent, "x activates", items, profile="frontier")
    assert v is not None and v["new_link"]
    assert ev.propose(client, "google", parent, "x activates", [], profile="frontier") is not None   # the target alone

"""Informativeness (alternatives the decisive experiment discriminates) and evidence-guided evolution (offline: fake client)."""
from pathlib import Path

import yaml

from hyparena.card import evolve, informativeness
from hyparena.card.models import HypothesisCard, Verification
from hyparena.card.pipeline import run
from hyparena.card.rules import finalize
from hyparena.llm.fake import FakeLLMClient

FIX = Path(__file__).parent / "fixtures" / "cards"
TEXT = ("Hypothesis: Resveratrol extends lifespan in mice.\n\nDecisive experiment: pair-fed controls and measured food "
        "intake in treated and control mice, with survival followed to death.")


def card_and_ver():
    d = yaml.safe_load((FIX / "ex5_resveratrol_endpoint.yaml").read_text(encoding="utf-8"))
    card = HypothesisCard.model_validate(d["card"])
    return card, finalize(card, Verification.model_validate(d["verification"]))


def test_informativeness_counts_the_alternatives_whose_control_is_quoted_from_the_text():
    card, ver = card_and_ver()
    info = informativeness.discriminated(FakeLLMClient(), "google", TEXT, card, ver)
    assert info["n"] == 1 and info["of"] >= 2 and TEXT.startswith(info["items"][0]["how"])


def test_informativeness_drops_a_phrase_that_is_not_in_the_text_and_unknown_ids(monkeypatch):
    card, ver = card_and_ver()
    first = informativeness.candidates(ver)[0].id
    reply = {"discriminated": [{"id": first, "how": "a control the text never mentions"}, {"id": "alt99", "how": "pair-fed controls"}]}
    monkeypatch.setattr(informativeness, "ask", lambda *a, **k: (reply, "google"))
    assert informativeness.discriminated(None, "google", TEXT, card, ver)["n"] == 0


def test_informativeness_is_capped_at_four(monkeypatch):
    card, ver = card_and_ver()
    ids = [a.id for a in informativeness.candidates(ver)]
    reply = {"discriminated": [{"id": i, "how": "pair-fed controls"} for i in ids * 2]}
    monkeypatch.setattr(informativeness, "ask", lambda *a, **k: (reply, "google"))
    assert informativeness.discriminated(None, "google", TEXT, card, ver)["n"] == min(4, len(ids))


def test_the_pipeline_flag_writes_informativeness_into_extra():
    res = run([TEXT], config="configs/v2-flash.yaml", fake=True, dedup=False, informativeness=True)
    assert res["items"][0]["extra"]["informativeness"] in range(0, 5)
    assert res["items"][0]["indicators"]["informativeness"] is not None


def test_similar_and_the_child_format():
    assert evolve.similar(TEXT, TEXT) and not evolve.similar(TEXT, "Completely different words about nematodes and heat.")
    child = {"text": "Resveratrol, 300 ppm, Extends Lifespan\n\nHypothesis: x.\n\nDecisive experiment: y.", "kind": "narrow_context", "change": "c"}
    assert evolve._validate({"children": [child]}, 1, TEXT, "resveratrol") == []
    assert evolve._validate({"children": [{**child, "kind": "other"}]}, 1, TEXT, "resveratrol")
    assert evolve._validate({"children": [{**child, "text": "Hypothesis: x. Decisive experiment: y."}]}, 1, TEXT, "resveratrol")
    assert evolve._validate({"children": [{**child, "text": TEXT}]}, 1, TEXT, "resveratrol")      # copies the parent


def test_select_parents_takes_the_top_ranked_unused():
    res = {"items": [{"id": f"H-000{i}", "outcome": "ranked" if i != 3 else "filtered", "verification": {"claims": []}} for i in range(1, 6)],
           "ranking": {"evidence_first": {"order": ["H-0003", "H-0002", "H-0005", "H-0001", "H-0004"]}}}
    assert evolve.select_parents(res, 2, set()) == ["H-0002", "H-0005"]
    assert evolve.select_parents(res, 2, {"H-0002"}) == ["H-0005", "H-0001"]


def test_children_get_fresh_ids_everywhere():
    res = {"items": [{"id": "H-0001"}, {"id": "H-0002"}], "calls": []}
    child = {"items": [{"id": "H-0001", "card": {"id": "H-0001", "raw_id": "H-0001"}, "verification": {"card_id": "H-0001",
                                                                                                          "alternatives": [{"ref": "H-0002"}]}},
                       {"id": "H-0002", "card": {"id": "H-0002"}, "verification": {"card_id": "H-0002"}}], "calls": [{"k": 1}]}
    ids = evolve.append_children(res, child, [{"parent": "H-0001", "kind": "narrow_context", "change": "a"}, {"parent": "H-0002", "kind": "add_mechanism", "change": "b"}], 1)
    assert ids == ["H-0003", "H-0004"]
    new = res["items"][2]
    assert new["card"]["id"] == "H-0003" and new["verification"]["card_id"] == "H-0003" and new["verification"]["alternatives"][0]["ref"] == "H-0004"
    assert new["origin"] == "evolved" and new["parent"] == "H-0001" and new["round"] == 1 and res["calls"] == [{"k": 1}]


def test_one_round_of_evolution_with_the_fake_client_ranks_the_child_with_its_parents():
    parent = run([TEXT, TEXT.replace("Resveratrol", "Metformin")], config="configs/v2-flash.yaml", fake=True, dedup=False)
    res = evolve.evolve(parent, "configs/v2-flash.yaml", rounds=1, parents=1, children=1, writer="google", verifiers=["deepseek"],
                        max_calls=400, fake=True)
    kids = [x for x in res["items"] if x.get("origin") == "evolved"]
    assert len(kids) == 1 and kids[0]["parent"] in {x["id"] for x in parent["items"]} and kids[0]["kind"] == "test_alternative"
    assert kids[0]["id"] in res["ranking"]["evidence_first"]["order"]
    c = res["meta"]["evolution"]["criterion"]
    assert c["n_children"] == 1 and c["children"][0]["place"] is not None

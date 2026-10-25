"""The top without relatives: one hypothesis per family, in the order of the profile; the ranking itself is not changed."""
from hyparena import diversity


def _res(order, parents=None):
    items = [{"id": h, "card": None, "parent": (parents or {}).get(h)} for h in order]
    return {"items": items, "ranking": {"p": {"order": order}}}


def test_one_per_family_in_profile_order():
    res = _res(["a", "b", "c", "d", "e"])
    rels = [{"a": "a", "b": "b", "types": ["variant"]}, {"a": "b", "b": "d", "types": ["duplicate"]},
            {"a": "c", "b": "e", "types": ["analog"]}]
    out = diversity.top_distinct(res, rels)
    assert [r["id"] for r in out["profiles"]["p"]] == ["a", "c"]
    assert out["profiles"]["p"][0]["hidden"] == ["b", "d"] and out["profiles"]["p"][1]["place"] == 3
    assert sorted(map(sorted, out["families"])) == [["a", "b", "d"], ["c", "e"]]


def test_weak_relations_do_not_make_a_family():
    res = _res(["a", "b", "c"])
    rels = [{"a": "a", "b": "b", "types": ["analog_weak"]}, {"a": "b", "b": "c", "types": ["competitor", "contradiction", "mechanism_neighbour"]}]
    assert [r["id"] for r in diversity.top_distinct(res, rels)["profiles"]["p"]] == ["a", "b", "c"]


def test_a_descendant_belongs_to_the_family_of_its_parent():
    res = _res(["c1", "c2", "x", "p"], parents={"c1": "p", "c2": "p"})
    out = diversity.top_distinct(res, [])
    assert [r["id"] for r in out["profiles"]["p"]] == ["c1", "x"] and out["profiles"]["p"][0]["hidden"] == ["c2", "p"]


def test_the_ranking_is_left_alone():
    res = _res(["a", "b"])
    before = list(res["ranking"]["p"]["order"])
    diversity.top_distinct(res, [{"a": "a", "b": "b", "types": ["duplicate"]}])
    assert res["ranking"]["p"]["order"] == before

from hyparena import diagnostics as dg


def _items(rows):
    return [{"id": chr(97 + i), "outcome": "ranked", "indicators": r} for i, r in enumerate(rows)]


def _ranking(order, e=None):
    e = e or {h: 1 - i / 10 for i, h in enumerate(order)}
    return {"order": order, "expected": e, "std": {h: 0.001 for h in order}, "K": 10000}


def test_a_pool_with_one_varying_indicator_is_warned_about():
    items = _items([{"a": "x", "b": "y", "c": None}] * 4 + [{"a": "z", "b": "y", "c": None}] * 2)
    d = dg.pool_diagnostics(items, {"p": _ranking(list("abcdef"))}, ["a", "b", "c"])
    assert d["varying"] == ["a"] and d["constant"] == ["b"] and d["all_unknown"] == ["c"]
    assert any("only 1 of 3" in w for w in d["warnings"])


def test_pairs_ordered_counts_groups_on_equal_footing():
    same = {h: 0.5 for h in "abcd"}                                  # one group of four: no pair is ordered
    assert dg.pairs_ordered(_ranking(list("abcd"), same)) == 0.0
    assert dg.pairs_ordered(_ranking(list("abcd"))) == 1.0           # a clear gap everywhere
    items = _items([{"a": i, "b": i % 2, "c": i % 3} for i in range(6)])
    d = dg.pool_diagnostics(items, {"flat": _ranking(list("abcdef"), {h: 0.5 for h in "abcdef"})}, ["a", "b", "c"])
    assert d["pairs_ordered"]["flat"] == 0.0 and any("flat 0%" in w for w in d["warnings"])


def test_a_healthy_pool_has_no_warning_and_a_tiny_pool_is_not_diagnosed():
    items = _items([{"a": i, "b": i % 2, "c": i % 3} for i in range(6)])
    assert dg.pool_diagnostics(items, {"p": _ranking(list("abcdef"))}, ["a", "b", "c"])["warnings"] == []
    assert dg.pool_diagnostics(_items([{"a": 1}] * 3), {"p": _ranking(list("abc"))}, ["a"])["warnings"] == []


def test_the_leading_indicator_is_the_one_that_creates_the_ordered_pairs():
    order = list("abcdef")
    ranked = [{"id": h, "indicators": {"a": i, "b": "same", "c": None}} for i, h in enumerate(order)]   # only "a" differs
    lead = dg.leading_indicator(ranked, _ranking(order), ["a", "b", "c"])
    assert lead["id"] == "a" and lead["share"] == 1.0 and lead["ordered_pairs"] == 15
    d = dg.pool_diagnostics([{"outcome": "ranked", "indicators": x["indicators"]} | {"id": x["id"]} for x in ranked],
                            {"p": _ranking(order)}, ["a", "b", "c"])
    assert any("essentially one indicator" in w and "a makes 100%" in w for w in d["warnings"])


def test_two_indicators_share_the_pairs_and_no_single_one_leads_alone():
    order = list("abcdef")
    ranked = [{"id": h, "indicators": {"a": i, "b": i}} for i, h in enumerate(order)]           # both differ in every pair
    lead = dg.leading_indicator(ranked, _ranking(order), ["a", "b"])
    assert lead["shares"]["a"] == lead["shares"]["b"] == 0.5 and lead["share"] == 0.5
    d = dg.pool_diagnostics([{"outcome": "ranked", "indicators": x["indicators"]} | {"id": x["id"]} for x in ranked],
                            {"p": _ranking(order)}, ["a", "b"])
    assert not any("essentially one indicator" in w for w in d["warnings"])

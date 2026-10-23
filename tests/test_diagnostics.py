from hyparena import diagnostics as dg


def _items(rows):
    return [{"outcome": "ranked", "indicators": r} for r in rows]


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

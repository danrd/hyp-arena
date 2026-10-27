from scripts.naive_baseline import MIN_POSITIVES, compound_units, naive_scores, paired


def _res(levels):
    items = [{"id": f"h{i}", "outcome": "ranked" if lv != "F" else "filtered", "indicators": {"path_to_human": lv if lv not in ("F", None) else None}}
             for i, lv in enumerate(levels)]
    return {"meta": {"ids": [f"imp{i:03d}" for i in range(len(levels))]}, "items": items}


def test_naive_order_puts_the_approved_first_the_unknown_after_the_last_level_and_filtered_last():
    res = _res(["0", "1", None, "F"])
    sc = naive_scores(res, {f"imp{i:03d}" for i in range(4)})
    vals = [sc[f"imp{i:03d}"][0] for i in range(4)]
    assert vals == [0.0, -1.0, -2.0, -3.0] and all(v[1] == 0.0 for v in sc.values())


def test_paired_difference_is_zero_for_identical_orders_and_positive_for_a_better_rank():
    units = [{"compound": str(i), "ours": (float(i), 0.0), "naive": (float(i), 0.0), "label": int(i >= 20)} for i in range(40)]
    r = paired(units, draws=300)
    assert r["diff"] == 0 and r["status"] == "fail"           # not above 0: the rule says fail
    better = [dict(u, naive=(float(i % 3), 0.0)) for i, u in enumerate(units)]
    r = paired(better, draws=300)
    assert r["diff"] > 0.3 and r["status"] == "pass"


def test_too_few_positives_is_uninformative():
    units = [{"compound": str(i), "ours": (float(i), 0.0), "naive": (0.0, 0.0), "label": int(i < MIN_POSITIVES - 1)} for i in range(40)]
    assert paired(units, draws=100)["status"] == "uninformative"

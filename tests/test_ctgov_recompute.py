import math

from scripts.ctgov_recompute import _sd, compare


def _m(groups, values, n, param="MEAN", disp="Standard Deviation", cats=1):
    meas = [{"groupId": g, "value": v[0], "spread": v[1]} for g, v in zip(groups, values)]
    return {"groups": [{"id": g, "title": t} for g, t in groups.items()] if isinstance(groups, dict) else [],
            "paramType": param, "dispersionType": disp,
            "denoms": [{"counts": [{"groupId": g, "value": str(k)} for g, k in n.items()]}],
            "classes": [{"categories": [{"measurements": meas}] * cats}]}


def test_sd_conversions():
    assert _sd("2", 25, "Standard Deviation", None, None) == 2.0
    assert _sd("2", 25, "Standard Error", None, None) == 10.0
    assert math.isclose(_sd(None, 16, "95% Confidence Interval", "0", "3.92"), 4.0)


def test_compare_needs_one_control_and_one_category():
    g = {"A": "Exercise", "B": "Placebo"}
    m = _m(g, [("5", "2"), ("0", "2")], {"A": 30, "B": 30})
    comps, why = compare(m)
    assert why == "" and comps[0]["significant"] and comps[0]["control"] == "Placebo"
    assert compare(_m({"A": "Dose 1", "B": "Dose 2"}, [("5", "2"), ("0", "2")], {"A": 30, "B": 30}))[0] == []
    assert compare(_m(g, [("5", "2"), ("0", "2")], {"A": 30, "B": 30}, cats=2))[1] == "several classes or categories"


def test_counts_use_fisher():
    m = _m({"A": "Intervention", "B": "Usual care"}, [("2", None), ("15", None)], {"A": 30, "B": 30}, param="COUNT_OF_PARTICIPANTS")
    comps, _ = compare(m)
    assert comps[0]["p"] < 0.01 and comps[0]["diff"] < 0

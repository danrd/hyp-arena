"""The profile report on a tiny synthetic bundle (no saved runs needed)."""
import json

from scripts import profile_report as pr

SPECS = [{"id": "a", "kind": "ordinal", "levels": ["no", "yes"]}, {"id": "b", "kind": "ordinal", "levels": ["no", "yes"]},
         {"id": "c", "kind": "cardinal"}]


def _bundle():
    hyps = [{"id": f"h{i}", "outcome": "ranked", "indicators": {"a": "yes" if i < 5 else "no", "b": "yes" if i < 5 else "no", "c": 1.0}}
            for i in range(10)] + [{"id": "x", "outcome": "filtered", "indicators": {}}]
    order = [f"h{i}" for i in range(10)]
    P = {n: {"order": order, "expected": {h: 1 - i / 10 for i, h in enumerate(order)},
             "std": {h: 0.01 for h in order}, "K": 10000, "p_topk": {h: 0.3 for h in order}} for n in ("p1", "p2")}
    return {"title": "t", "meta": {"indicators": SPECS}, "hypotheses": hyps, "profiles": P}


def test_constant_and_duplicated_indicators_are_named(tmp_path):
    f = tmp_path / "b.json"
    f.write_text(json.dumps(_bundle()))
    r = pr.report(str(f))
    by = {x["id"]: x for x in r["indicators"]}
    assert r["ranked"] == 10 and by["c"]["constant"] and not by["a"]["constant"]
    top = r["correlations"]["pairs"][0]
    assert {top["a"], top["b"]} == {"a", "b"} and abs(top["rho"] - 1) < 1e-9
    assert abs(r["profiles"]["tau"]["p1 / p2"] - 1) < 1e-9 and r["profiles"]["top3_overlap"]["p1 / p2"] == 3
    assert 0 <= r["profiles"]["pairs_ordered"]["p1"] <= 1

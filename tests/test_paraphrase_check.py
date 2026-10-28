from scripts.paraphrase_check import agreement, verdict


def _it(status="supported", place="1", sub="a", ctx=("m",)):
    return {"outcome": "ranked", "status": status, "place": place, "facets": {"subject": sub, "relation": "r", "object": "o", "context": ctx}}


def test_agreement_counts_equal_facets_statuses_and_overlapping_places():
    a = {"items": [_it(place="1-3"), _it(sub="x")]}
    b = {"items": [_it(place="3-5"), _it(sub="y", status="refuted", place="9")]}
    r = agreement(a, b)
    assert r["subject"] == 0.5 and r["relation"] == 1.0 and r["status"] == 0.5 and r["place"] == 0.5


def test_verdict_passes_only_if_every_measure_is_within_the_repeat_minus_the_tolerance():
    rep = {k: 0.9 for k in ("subject", "relation", "object", "context", "status", "place")}
    ok = dict(rep, status=0.86)
    bad = dict(rep, status=0.8)
    assert verdict(ok, rep)["status"] == "pass" and verdict(bad, rep)["status"] == "fail"

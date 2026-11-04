import json

from scripts.extraction_gold_v3 import baselines, measure, record_for

SOURCE = ("Exercise in old age. Sixty-six healthy older adults were randomised to training or control. "
          "Grip strength rose by 2.4 kg (p = 0.01) after training.")


def _reply(**kw):
    r = {"pmid": "1", "quote": "Grip strength rose by 2.4 kg (p = 0.01) after training.", "quote_role": "finding",
         "stance": "supports", "study_type": "rct", "effect_percent": None, "design": "rct", "n_total": 66,
         "n_quote": "Sixty-six healthy older adults", "comparison": "between_groups", "effect_reported": "2.4 kg",
         "effect_class": "medium"}
    r.update(kw)
    return json.dumps({"records": [r]})


def test_record_applies_the_code_checks():
    p = record_for([_reply()], "1", SOURCE)
    assert p["n_total"] == 66 and p["design"] == "rct" and p["effect_reported"] == "2.4 kg"
    p = record_for([_reply(n_quote="66 adults")], "1", SOURCE)          # phrase not in the abstract: the number goes too
    assert p["n_total"] is None
    assert record_for([_reply(quote="invented sentence")], "1", SOURCE) is None
    assert record_for([_reply(pmid="2")], "1", SOURCE) is None
    assert record_for(["not json", _reply()], "1", SOURCE)["design"] == "rct"   # the last parsed reply counts


def test_measure_counts_a_missing_record_as_wrong():
    gold = [{"pair_id": "a", "design": "rct", "comparison": "between_groups", "n_total": 66, "effect_class": "medium",
             "effect_reported": "+2.4 kg"},
            {"pair_id": "b", "design": "animal", "comparison": "between_groups", "n_total": None, "effect_class": "unclear",
             "effect_reported": ""}]
    pred = {"a": record_for([_reply()], "1", SOURCE), "b": None}
    m = measure(gold, pred)
    assert m["with_record"] == 1 and m["design"] == 0.5 and m["n_total"] == 0.5
    assert m["effect_number"] == {"gold_with_number": 1, "found": 1}
    assert m["status"] == "not passed"
    assert measure(gold, pred, v5=True)["design"] == 0.5
    assert baselines(gold)["comparison"] == 1.0

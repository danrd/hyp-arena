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


def test_effect_class_rule_a():
    from hyparena.card.effect_class import effect_class, from_phrase
    assert from_phrase("odds ratio = 4.89, 95% CI 1.89-11.27") == "large"
    assert from_phrase("relative risk = 1.60, 95% CI: 1.03-2.49") == "medium"
    assert from_phrase("HR 0.79 (0.65-0.96)") == "medium" and from_phrase("RR 1.10 (95% CI 0.58, 2.07)") == "small"
    assert from_phrase("d = 0.45") == "small" and from_phrase("Hedges' g = 0.9") == "large"
    assert from_phrase("9.3% increase") == "medium" and from_phrase("reduced by 35%") == "large" and from_phrase("+3%") == "small"
    assert from_phrase("up to 8-fold") == "large" and from_phrase("a modest improvement") == "small"
    assert from_phrase("strength increased by 40 +/- 6 percent") == "large" and from_phrase("rose by about 12%") == "medium"
    assert from_phrase("(20%, p < 0.05)") == "unclear" and from_phrase("decreased from 65.7% to 42.9%") == "unclear"
    for raw in ("+2.4 kg", "58±11 m", "F(3,146)=16.16", "p < 0.001", ""):
        assert from_phrase(raw) == "unclear"
    assert effect_class("odds ratio = 4.89", "none") == "none" and effect_class("+2.4 kg", "large") == "unclear"


def test_review_keeps_design_review():
    p = record_for([_reply(design="rct")], "1", SOURCE, review=True)
    assert p["design"] == "review"
    assert record_for([_reply(design="meta_analysis")], "1", SOURCE, review=True)["design"] == "meta_analysis"


def test_measure_v3_relevance_and_baselines():
    from scripts.extraction_gold_v3 import measure_v3
    g = {"design": "rct", "comparison": "between_groups", "n_total": 66, "effect_class": "medium", "effect_reported": "2.4 kg"}
    gold = [{"pair_id": "a", "relevant": True, **g}, {"pair_id": "b", "relevant": False}, {"pair_id": "c", "relevant": False}]
    pred = {"a": record_for([_reply()], "1", SOURCE), "b": record_for([_reply(stance="neither")], "1", SOURCE), "c": None}
    m = measure_v3(gold, pred)
    assert m["relevance"] == {"accuracy": 1.0, "recall": 1.0, "precision": 1.0, "baseline": 0.67}
    assert m["extraction"]["design"] == 1.0
    assert "effect_class" in m["failed"]          # the phrase "2.4 kg" is raw units: unclear by rule A, gold says medium
    assert "comparison" in m["failed"]            # 1.0 equals the constant baseline of one pair: not passed


def test_relevance_check_targets_and_merge():
    from hyparena.card.verifier import merge_relevance, relevance_targets
    abstracts = {"1": {"title": "Exercise in old age.", "abstract": SOURCE.split(". ", 1)[1]}}
    neither = json.loads(_reply(stance="neither", intervention_match="exact"))["records"]
    assert relevance_targets(neither, abstracts) == ["1"]
    assert relevance_targets(json.loads(_reply())["records"], abstracts) == []          # already has a stance
    q = "Grip strength rose by 2.4 kg (p = 0.01) after training."
    ok = {"pmid": "1", "intervention": "same_kind", "outcome": "same_domain", "result": "supports", "quote": q}
    m = merge_relevance(neither, [ok], abstracts)[0]
    assert m["stance"] == "supports" and m["intervention_match"] == "class" and "relevance_check" in m["flags"]
    assert neither[0]["stance"] == "neither"                                             # pure: the input is not changed
    for bad in ({**ok, "outcome": "different"}, {**ok, "result": "none"}, {**ok, "quote": "not in the abstract"}):
        assert merge_relevance(neither, [bad], abstracts)[0]["stance"] == "neither"


def test_record_for_applies_saved_relevance_answers():
    rep = _reply(stance="neither")
    chk = json.dumps({"relevance": {"pmid": "1", "intervention": "same", "outcome": "same", "result": "refutes",
                                    "quote": "Grip strength rose by 2.4 kg (p = 0.01) after training."}})
    assert record_for([rep], "1", SOURCE, by_stance=True)["relevant"] is False
    assert record_for([rep, chk], "1", SOURCE, by_stance=True)["relevant"] is True


def test_rescore_v3_counts_no_stance_records_only_in_the_sensitivity(monkeypatch):
    from hyparena.card import rules_v3
    from scripts.calibration import rescore_v3
    seen = []
    monkeypatch.setattr(rules_v3, "evaluate", lambda card, claims, alts, variant="v3": seen.append([len(c.evidence) for c in claims])
                        or type("R", (), {"as_dict": lambda self: {"P": 0.5}})())
    rec = {"source": "PubMed", "record_id": "PMID:1", "qualifiers_match": {"intervention_match": "class"}}
    other = {**rec, "record_id": "PMID:2", "qualifiers_match": {"intervention_match": "different"}}
    import yaml
    from pathlib import Path
    card = yaml.safe_load((Path(__file__).parent / "fixtures" / "cards" / "ex2_senolytics_function.yaml").read_text())["card"]
    res = {"u": {"items": [{"card": card, "v3": {}, "verification": {"card_id": "H-0001",
                                                                       "claims": [{"id": "c1", "no_stance": [rec, other]}]}}]}}
    rescore_v3(res)
    rescore_v3(res, no_stance_as_support=True)
    assert seen == [[0], [1]]                     # only the same-class record counts, and only in the sensitivity

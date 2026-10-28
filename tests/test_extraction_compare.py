from scripts.extraction_compare import compare, gold_cells, kg_cells, record_cells, totals


def _g(name, sp, pct, sig, sex="Male", mx=""):
    return {"compound_name": name, "species": sp, "avg_lifespan_change_percent": pct, "avg_lifespan_significance": sig,
            "max_lifespan_change_percent": mx, "max_lifespan_significance": "NS" if mx else "NA", "gender": sex}


def test_gold_direction_follows_significance_and_sign_and_unknown_sex_matches_both():
    cells = gold_cells([_g("Aluminium chloride", "Mus musculus", "-7", "S"), _g("X", "Mus musculus", "9", "NS", sex="Unknown")])
    assert [(c["direction"], c["sex"]) for c in cells] == [("decrease", "male"), ("no_effect", "any")]


def test_compound_names_match_by_spelling_and_by_distinctive_words():
    gold = gold_cells([_g("Aluminium chloride", "Mus musculus", "-7", "S"), _g("Thymus extract", "Mus musculus", "28", "S", sex="Female")])
    kg = [{"organism": {"species": "Mus musculus", "sex": "male"}, "outcome": {"endpoint": "lifespan"}, "provenance": {"quote_role": "finding"},
           "intervention": {"label": "aluminum chloride"}, "result": {"direction": "decrease", "significance": "S"}},
          {"organism": {"species": "Mus musculus", "sex": "female"}, "outcome": {"endpoint": "lifespan"}, "provenance": {"quote_role": "finding"},
           "intervention": {"label": "thymus-derived polypeptide factors (TF)"}, "result": {"direction": "increase", "significance": "S"}}]
    r = compare(gold, kg_cells(kg))
    assert r["found"] == 2 and r["correct"] == 2 and r["pred_right"] == 2


def test_not_significant_rows_count_as_no_effect_and_missing_or_wrong_direction_is_counted():
    gold = gold_cells([_g("Beta-carotene", "Mus musculus", "-10", "NS"), _g("Foo", "Mus musculus", "20", "S", sex="Male")])
    pred = record_cells([{"endpoint": "lifespan", "quote_role": "finding", "effect": "decrease", "species": "mouse", "sex": "male"}], "Foo")
    r = compare(gold, pred)
    assert r["gold_cells"] == 2 and r["found"] == 1 and r["correct"] == 0
    t = totals([r])
    assert t["found_rate"] == 0.5 and t["correct_rate"] == 0.0 and t["precision"] == 1.0 and t["direction_given_found"] == 0.0

from scripts.reading.functional_outcome_retention import validated_outcomes


def test_trim_label_keep_two_distinct_source_comparisons():
    treated = "Walking speed improved compared with usual care."
    genotype = "Walking speed was unchanged after the second comparison."
    abstracts = {"1": {"abstract": f"We measured usual walking speed. {treated} {genotype}"}}
    first = {"source_pmid": "1", "measure": "usual walking speed", "excerpt": treated}
    second = {"source_pmid": "1", "measure": "Walking speed", "excerpt": genotype}
    rows, errors = validated_outcomes({"paper_outcomes": [first, second, second]}, abstracts, repair=True)
    assert rows[0]["measure"] == "Walking speed"
    assert rows[0]["original_measure"] == first["measure"]
    assert rows[0]["excerpt"] == treated
    assert rows[1] == second
    assert errors == ["duplicate measure"]


def test_reject_new_measure_or_unverified_excerpt():
    good = "Mean percent ulcer area declined."
    abstracts = {"1": {"abstract": f"We measured mean percent ulcer reepithelialization. {good}"}}
    result = {"source_pmid": "1", "measure": "mean percent ulcer reepithelialization", "excerpt": good}
    rows, errors = validated_outcomes({"paper_outcomes": [result, {**result, "excerpt": good.replace("declined", "increased")}]},
                                      abstracts, repair=True)
    assert not rows
    assert errors == ["measure missing from quote", "unverified quote"]

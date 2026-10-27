"""The paired name-dependence check: masking by token and the agreement counts (no model calls)."""
from scripts import blind_check as bc


def test_masking_replaces_whole_tokens_case_insensitively_and_leaves_the_rest():
    text = "Rapamycin extends life. rapamycin-treated mice; RAPAMYCIN. Sirolimus is the same. Rapamycinase is another word."
    out, n = bc.mask(text, ["Rapamycin", "Sirolimus"])
    assert out == "Compound-X extends life. Compound-X-treated mice; Compound-X. Compound-X is the same. Rapamycinase is another word."
    assert n == 4


def test_longer_names_are_masked_first():
    out, n = bc.mask("17-alpha-estradiol and 17-alpha-estradiol benzoate", ["17-alpha-estradiol", "17-alpha-estradiol benzoate"])
    assert "estradiol" not in out.replace("Compound-X", "") and n == 2


def test_compare_counts_papers_and_fields():
    r = lambda p, **k: {"pmid": p, "stance": "supports", "effect": "increase", "endpoint": "lifespan", "quote_role": "finding", **k}
    a = [[r("1"), r("2")], [], [r("3")]]
    b = [[r("1", stance="neither"), r("2")], [], [r("4")]]
    c = bc.compare(a, b)
    assert c["same_paper_set"] == 2 and c["both_empty"] == 1 and c["shared_records"] == 2
    assert c["stance_agree"] == 1 and c["effect_agree"] == 2 and c["paper_overlap"] == "2/4"


def _answer(i, records, tokens_out=300, error=None):
    import json
    return {"i": i, "text": json.dumps({"records": records}), "tokens_in": 2000, "tokens_out": tokens_out, "error": error, "model": "m"}


def _thresholds():
    return {"stance_agree_min": 0.92, "effect_agree_min": 0.91, "set_agree_min": 0.728, "valid_rate_min": 0.95,
            "truncated_rate_max": 0.05, "shared_records_min": 4, "completion_token_cap": 4000, "mini_sample": {"valid_min": 7, "truncated_max": 1}}


def test_mini_sample_takes_four_with_records_and_four_empty():
    items = [{"orig": [{"pmid": "1"}] if i % 2 == 0 else []} for i in range(20)]
    idx = bc.mini_indices(items)
    assert len(idx) == 8 and sum(bool(items[i]["orig"]) for i in idx) == 4


def test_candidate_verdict_passes_a_faithful_candidate_and_fails_a_disagreeing_one(tmp_path):
    import json
    rec = lambda p, **k: {"pmid": p, "stance": "supports", "effect": "increase", "endpoint": "lifespan", "quote_role": "finding", **k}
    orig = {str(i): ([rec(str(i))] if i < 5 else []) for i in range(8)}
    good = [_answer(i, orig[str(i)]) for i in range(8)]
    f = tmp_path / "good.json"
    f.write_text(json.dumps({"n_items": 8, "orig": orig, "answers": good}))
    v = bc.candidate_verdict(str(f), _thresholds())
    assert v["status"] == "pass" and v["stance_rate"] == 1.0 and v["set_rate"] == 1.0
    bad = [_answer(i, [rec(str(i), stance="neither", effect="unknown")] if i < 5 else []) for i in range(8)]
    g = tmp_path / "bad.json"
    g.write_text(json.dumps({"n_items": 8, "orig": orig, "answers": bad}))
    assert bc.candidate_verdict(str(g), _thresholds())["status"] == "fail"


def test_candidate_verdict_is_uninformative_with_too_few_shared_records_and_flags_truncation(tmp_path):
    import json
    orig = {str(i): [] for i in range(8)}
    f = tmp_path / "few.json"
    f.write_text(json.dumps({"n_items": 8, "orig": orig, "answers": [_answer(i, []) for i in range(8)]}))
    assert bc.candidate_verdict(str(f), _thresholds())["status"] == "uninformative"
    t = tmp_path / "trunc.json"
    t.write_text(json.dumps({"n_items": 8, "orig": orig, "answers": [_answer(i, [], tokens_out=4000) for i in range(8)]}))
    out = bc.candidate_verdict(str(t), _thresholds(), mini=True)
    assert out["truncated"] == 8 and out["accepted_for_full_run"] is False


def test_counted_keys_follow_the_effect_direction_for_lifespan_findings_and_the_stance_otherwise():
    from scripts.blind_check import counted_keys, status_compare
    a = [{"pmid": "1", "endpoint": "lifespan", "quote_role": "finding", "effect": "increase", "stance": "neither"},
         {"pmid": "2", "endpoint": "biomarker", "quote_role": "finding", "effect": "increase", "stance": "neither"},
         {"pmid": "3", "endpoint": "biomarker", "quote_role": "finding", "effect": "unknown", "stance": "refutes"}]
    assert counted_keys(a) == {("1", "L", "increase"), ("3", "S", "refutes")}
    b = [{"pmid": "1", "endpoint": "lifespan", "quote_role": "finding", "effect": "increase", "stance": "supports"}]
    r = status_compare([a], [b])
    assert r["same_counted_set"] == 0 and r["counted_union"] == 2 and abs(r["jaccard"] - 0.5) < 1e-9

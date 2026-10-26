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

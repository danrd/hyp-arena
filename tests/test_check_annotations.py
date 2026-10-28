from scripts.check_annotations import problems

SRC = {"papers": [{"pmid": "1", "title": "t", "abstract": "Drug X did not extend lifespan in mice.  Background is here."}]}


def _rec(**kw):
    r = {"quote": "Drug X did not extend lifespan in mice.", "quote_role": "finding", "intervention": "Drug X", "endpoint": "lifespan",
         "effect": "no_effect", "significance": "not_significant", "species": "mouse", "strain": "", "sex": "unspecified", "dose": "",
         "system": "in_vivo", "ambiguous": False}
    r.update(kw)
    return r


def test_a_valid_annotation_has_no_problems():
    assert problems({"papers": [{"pmid": "1", "records": [_rec()], "no_relevant_finding": False, "ambiguous": False, "note": ""}]}, SRC) == []


def test_non_verbatim_quote_bad_value_and_wrong_order_are_found():
    bad = {"papers": [{"pmid": "1", "records": [_rec(quote="Drug X extended lifespan.", effect="up")], "no_relevant_finding": False}]}
    msgs = problems(bad, SRC)
    assert any("verbatim" in m for m in msgs) and any("effect" in m for m in msgs)
    assert problems({"papers": [{"pmid": "2", "records": [], "no_relevant_finding": True}]}, SRC)

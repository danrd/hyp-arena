"""Site bundle: export from a saved v2 run joins the tournament by pool ids; embed replaces the page's example."""
import json

from hyparena import site


def _v2(tmp_path):
    item = lambda i, outcome: {"id": f"H-000{i}", "text": f"Hypothesis: compound {i} extends lifespan in mice.\nMore.",
                               "outcome": outcome, "card": None, "verification": None, "indicators": None}
    res = {"meta": {"as_of": "2010-12-31", "calls": 3, "profiles": {}, "indicators": [], "k_top": 1},
           "items": [item(1, "ranked"), item(2, "filtered")],
           "ranking": {"evidence_first": {"order": ["H-0001"], "expected": {"H-0001": 0.3}, "quantiles": {"H-0001": [0.1, 0.3, 0.5]},
                                          "p_topk": {"H-0001": 1.0}, "p_best": {"H-0001": 1.0}, "pairwise": {"H-0001": {}}, "meta": {}}},
           "filtered": {"H-0002": "PMID:1"}, "known_results": [], "outcome_counts": {"ranked": 1, "filtered": 1}}
    (tmp_path / "v2.json").write_text(json.dumps(res))
    (tmp_path / "pool.json").write_text(json.dumps({"source": {}, "hypotheses": [{"id": 1, "title": "a", "text": "a"}, {"id": 2, "title": "b", "text": "b"}]}))
    (tmp_path / "elo.json").write_text(json.dumps({"config": {"rating": "elo"}, "matches": 1,
                                                   "hypotheses": {"imp001": {"combined": 1210, "status": "active"},
                                                                  "imp002": {"combined": 1190, "status": "active"}}}))
    return tmp_path


def test_export_joins_ids(tmp_path):
    d = _v2(tmp_path)
    b = site.export(str(d / "v2.json"), str(d / "elo.json"), str(d / "pool.json"))
    assert [h["id"] for h in b["hypotheses"]] == ["imp001", "imp002"]
    assert b["hypotheses"][0]["title"] == "compound 1 extends lifespan in mice."
    assert b["profiles"]["evidence_first"]["order"] == ["imp001"] and b["lists"]["filtered"] == {"imp002": "PMID:1"}
    assert b["elo"]["ratings"]["imp002"]["rating"] == 1190


def test_embed_replaces_the_example(tmp_path):
    page = tmp_path / "index.html"
    page.write_text('<script id="sample" type="application/json">{}</script>')
    (tmp_path / "b.json").write_text(json.dumps({"format": "hyparena-site@1", "q": "</script>"}))
    site.embed(str(tmp_path / "b.json"), page)
    assert "<\\/script>" in page.read_text() and page.read_text().count("</script>") == 1

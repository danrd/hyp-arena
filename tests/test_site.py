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


def test_export_carries_monte_carlo_error():
    # the page groups hypotheses by 1.96*sqrt((sA^2+sB^2)/K), so std and K must reach the bundle
    import inspect
    assert "std" in inspect.getsource(site.bundle_from_result) and "\"K\"" in inspect.getsource(site.bundle_from_result)


def test_docs_render_with_unique_anchors_and_no_vault_links():
    html = site.render_docs()
    assert html.count('<article class="doc"') == 8 and 'id="docToc"' in html
    assert "[[" not in html and "Working_Notes" not in html and "Open_Longevity" not in html
    for ex in ("ex1", "ex2", "ex3", "ex4", "ex5"):
        assert f'href="../?example={ex}#card"' in html


def test_build_writes_the_standalone_docs_page(tmp_path):
    page = tmp_path / "index.html"
    page.write_text('<meta name="hyparena-version" content="0"><link rel="stylesheet" href="x.css"><style>b{}</style>')
    site.build(page)
    s = (tmp_path / "docs" / "index.html").read_text()
    assert 'class="docs-layout"' in s and f'content="{site.code_version()}"' in s and 'href="../"' in s and "<style>b{}</style>" in s
    assert f'content="{site.code_version()}"' in page.read_text()

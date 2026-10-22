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


PAGES = ["method", "method/ranking", "reference", "reference/aggregation", "reference/examples", "start"]


def test_docs_pages_have_unique_anchors_and_no_vault_links():
    pages = site.load_pages()
    assert [p["slug"] for p in pages] == PAGES
    html = "".join(sec["html"] for p in pages for sec in p["sections"])
    assert "[[" not in html and "Working_Notes" not in html and "Open_Longevity" not in html
    for ex in ("ex1", "ex2", "ex3", "ex4", "ex5"):
        assert f'href="../../../?example={ex}#card"' in html


def _built(tmp_path):
    page = tmp_path / "index.html"
    page.write_text('<meta name="hyparena-version" content="0"><link rel="stylesheet" href="x.css"><style>b{}</style>')
    site.build(page)
    return {slug: (tmp_path / "docs" / slug / "index.html").read_text() for slug in PAGES}


def test_every_docs_link_resolves(tmp_path):
    import posixpath
    import re
    built = _built(tmp_path)
    ids = {slug: set(re.findall(r'\sid="([^"]+)"', text)) for slug, text in built.items()}
    for slug, text in built.items():
        for target in re.findall(r'<a [^>]*?href="([^"]*)"', text):
            if target.startswith(("http", "mailto")) or target == "":
                continue
            path, _, frag = target.partition("#")
            if not path:
                assert frag in ids[slug], (slug, target)
                continue
            if "?" in path:
                continue
            dest = posixpath.normpath(posixpath.join(slug, path))
            if dest.startswith(".."):
                continue                              # the home page
            assert dest in ids, (slug, target)
            if frag:
                assert frag in ids[dest], (slug, target)


def test_build_writes_the_pages_and_a_redirect(tmp_path):
    built = _built(tmp_path)
    for slug, s in built.items():
        assert f'content="{site.code_version()}"' in s and "<style>b{}</style>" in s and 'class="crumbs"' in s and 'aria-current="page"' in s
        assert 'id="docDrawer"' in s and 'id="docAside"' in s and 'class="pager"' in s
    red = (tmp_path / "docs" / "index.html").read_text()
    assert "location.replace" in red and '"card-layers": "method"' in red and '"docs-run": "start"' in red and 'const slug = map[h] || "method"' in red


def test_regimen_title_reads_from_the_label():
    lab = {"compound": "Rapamycin", "dose": "14 ppm food", "age_at_start": "9 months"}
    assert site._regimen_title(lab) == "Rapamycin, 14 ppm food, старт 9 мес"
    assert site._regimen_title({"compound": "X", "dose": "", "age_at_start": ""}) == "X"


def test_itp_bundle_from_the_saved_runs():
    import pytest
    from pathlib import Path
    dev, test = Path("runs/stage4/itp2010_dev.json"), Path("runs/stage4/itp2010_test.json")
    labels = Path("data/backtest/itp_2010-12-31_labels.json")
    if not (dev.exists() and test.exists() and labels.exists()):
        pytest.skip("the saved backtest runs are local (runs/ is not tracked)")
    b = site.export_itp(str(dev), str(test), str(labels))
    s = b["summary"]
    assert len(b["hypotheses"]) == s["n_tests"] == 70 and s["n_ranked"] + s["n_known"] + s["n_filtered"] == 70
    assert all(h["after"]["label"] in ("supports", "no_effect", "harmful") and h["after"]["pmids"] for h in b["hypotheses"])
    assert "late_start" not in [i["id"] for i in b["meta"]["indicators"]]
    assert set(b["profiles"]) == {"evidence_first", "cheap_feasible", "fundamental"}
    assert 0.6 < s["auc"]["per_regimen"]["auc"] < 0.9 and s["bottom"]["hits"] == 0
    assert {e["kind"] for e in b["showcase"]["examples"]} >= {"hit", "miss", "known", "filtered"}

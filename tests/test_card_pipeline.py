"""Pipeline machinery with the fake LLM and stubbed sources (no network)."""
from hyparena.card import pipeline, sources, verifier
from hyparena.tools import drug_phase, pubmed

ABSTRACT = {"pmid": "1", "title": "A fake compound extends lifespan in mice.", "year": "2020", "pubtypes": ["Journal Article"],
            "abstract": "We show that the fake compound extends median lifespan of mice by 12%.", "first_author": "X", "journal": "J"}


def test_pipeline_fake(monkeypatch):
    monkeypatch.setattr(pubmed, "search", lambda q, retmax=8, as_of=None: ["1"])
    monkeypatch.setattr(pubmed, "fetch", lambda ids: {"1": ABSTRACT})
    monkeypatch.setattr(verifier, "drugage_records", lambda claim, allowed=None: ([], []))
    monkeypatch.setattr(drug_phase, "max_phase", lambda name: 2)
    res = pipeline.run(["The fake compound extends the lifespan of mice.", "Another fake compound helps old mice."],
                       fake=True, K=2000)
    assert [x["outcome"] for x in res["items"]] == ["ranked", "ranked"]
    assert set(res["ranking"]) == {"evidence_first", "cheap_feasible", "fundamental"}
    x = res["items"][0]
    assert x["card"]["claims"][0]["source_span"] in x["text"]
    assert x["indicators"]["translational_distance"] == "phase2"
    assert any(c["kind"] == "search" for c in res["calls"]) and any(c.get("role") == "normalize_card" for c in res["calls"])


def test_quote_must_be_verbatim():
    probs = verifier._validate({"records": [{"pmid": "1", "quote": "extends median lifespan of mice by 12%"},
                                            {"pmid": "1", "quote": "doubles lifespan"}]}, {"1": ABSTRACT})
    assert len(probs) == 1 and "verbatim" in probs[0]

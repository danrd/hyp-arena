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


def _fixture_card(name):
    from pathlib import Path

    import yaml

    from hyparena.card.models import HypothesisCard
    d = yaml.safe_load((Path(__file__).parent / "fixtures" / "cards" / f"{name}.yaml").read_text(encoding="utf-8"))
    return HypothesisCard.model_validate(d["card"])


def _stub(monkeypatch, records):
    monkeypatch.setattr(pubmed, "search", lambda q, retmax=8, as_of=None: ["1"])
    monkeypatch.setattr(pubmed, "fetch", lambda ids: {"1": ABSTRACT})
    monkeypatch.setattr(verifier, "drugage_records", lambda claim, allowed=None: ([], []))
    monkeypatch.setattr(verifier, "ask", lambda *a, **k: ({"records": records}, "fake"))


def _record(**kw):
    return {"pmid": "1", "quote": "extends median lifespan of mice by 12%", "quote_role": "finding", "stance": "supports",
            "endpoint": "lifespan", "species": "mouse", **kw}


def test_rejected_alternative_is_verified(monkeypatch):
    card = _fixture_card("ex3_rapamycin_mechanism")
    assert "rapamycin slows aging mice" in verifier.queries(card.declared_alternatives[0], card)
    _stub(monkeypatch, [])
    ver = verifier.verify(None, ["google"], "openai", card)
    assert [cv.id for cv in ver.claims] == ["c1", "c2", "a1"]
    assert all(cv.added_claim is None for cv in ver.claims)


def test_inherited_mismatch_is_a_soft_refusal(monkeypatch):
    card = _fixture_card("ex2_senolytics_function")
    c1 = card.claims[0]                                   # species human inherited from PICO
    _stub(monkeypatch, [_record(qualifiers_match={"species": "no"})])
    cv = verifier.verify_claim(None, "google", frozenset(), c1, card)
    assert not cv.evidence and not cv.counterevidence
    assert [r.type for r in cv.refusals] == ["inherited_mismatch"]
    c4 = card.claims[3]                                   # species stated in the span (object): an ordinary record
    cv = verifier.verify_claim(None, "google", frozenset(), c4, card)
    assert len(cv.evidence) == 1 and not cv.refusals


def test_unknown_comparator_is_not_a_mismatch(monkeypatch):
    card = _fixture_card("ex5_resveratrol_endpoint")
    _stub(monkeypatch, [_record(stance="refutes", qualifiers_match={"species": "yes", "comparator": "no", "age_at_start": "no"})])
    cv = verifier.verify_claim(None, "google", frozenset(), card.claims[0], card)
    qm = cv.counterevidence[0].qualifiers_match
    assert qm["comparator"] == "n/a" and qm["age_at_start"] == "no"   # middle age is stated: a real mismatch stays


def test_truncated_reply_keeps_complete_records():
    full = '{"pmid": "1", "quote": "a", "stance": "supports"}'
    text = '```json\n{"records": [' + full + ', ' + full.replace('"1"', '"2"') + ', {"pmid": "3", "quote": "b", "sta'
    v = verifier.parse_records(text)
    assert [r["pmid"] for r in v["records"]] == ["1", "2"] and v["truncated"]
    assert verifier.parse_records('{"records": []}') == {"records": []}
    assert verifier._validate({"pmid": "1", "quote": "x"}, {"1": ABSTRACT})   # a lone record is not an answer


def test_quote_about_other_organisms_is_a_species_mismatch(monkeypatch):
    card = _fixture_card("ex5_resveratrol_endpoint")
    quote = "Resveratrol extends the lifespan of diverse species including yeast and Drosophila."
    abstract = {**ABSTRACT, "abstract": quote + " " + ABSTRACT["abstract"]}
    _stub(monkeypatch, [_record(quote=quote, qualifiers_match={"species": "yes"})])
    monkeypatch.setattr(pubmed, "fetch", lambda ids: {"1": abstract})
    cv = verifier.verify_claim(None, "google", frozenset(), card.claims[0], card)
    assert cv.evidence[0].qualifiers_match["species"] == "no"
    assert verifier.quote_organisms("in older adults and in mice") == {"human", "mouse"}


def test_cut_off_reply_goes_to_the_fallback_family(monkeypatch):
    card = _fixture_card("ex5_resveratrol_endpoint")
    _stub(monkeypatch, [])
    asked = []

    def ask(client, *, family, **kw):
        asked.append(family)
        return (None, family) if family == "google" else ({"records": [_record()]}, family)

    monkeypatch.setattr(verifier, "ask", ask)
    cv = verifier.verify_claim(None, "google", frozenset(), card.claims[0], card, fallback="zhipu")
    assert asked == ["google", "zhipu"] and len(cv.evidence) == 1


def test_stated_species_is_not_inherited():
    from hyparena.card.rules import mark_inherited
    card = _fixture_card("ex1_rapamycin_healthspan")
    c4 = card.claims[3]                                   # span "... in healthy older adults"
    c4.qualifiers["species"], c4.inherited_from_pico = "human", ["species"]
    assert mark_inherited(card).claims[3].inherited_from_pico == []


def test_unknown_species_is_not_a_mismatch(monkeypatch):
    card = _fixture_card("ex1_rapamycin_healthspan")
    c2 = card.claims[1]                                   # "slows multiple aspects of aging": no organism
    _stub(monkeypatch, [_record(qualifiers_match={"species": "no"})])
    cv = verifier.verify_claim(None, "google", frozenset(), c2, card)
    assert cv.evidence[0].qualifiers_match["species"] == "n/a"

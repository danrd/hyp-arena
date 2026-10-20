"""Pipeline machinery with the fake LLM and stubbed sources (no network)."""
from hyparena.card import pipeline, sources, verifier
from hyparena.tools import pubmed

ABSTRACT = {"pmid": "1", "title": "A fake compound extends lifespan in mice.", "year": "2020", "pubtypes": ["Journal Article"],
            "abstract": "We show that the fake compound extends median lifespan of mice by 12%.", "first_author": "X", "journal": "J"}


def test_pipeline_fake(monkeypatch):
    monkeypatch.setattr(pubmed, "search", lambda q, retmax=8, as_of=None: ["1"])
    monkeypatch.setattr(pubmed, "fetch", lambda ids: {"1": ABSTRACT})
    monkeypatch.setattr(verifier, "drugage_records", lambda claim, allowed=None, cid=None: ([], []))
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
    monkeypatch.setattr(verifier, "drugage_records", lambda claim, allowed=None, cid=None: ([], []))
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


def _expert_file(tmp_path, decisions, hypotheses=()):
    import yaml
    f = tmp_path / "expert.yaml"
    f.write_text(yaml.safe_dump({"decisions": decisions, "hypotheses": list(hypotheses)}, allow_unicode=True))
    return str(f)


def test_pipeline_with_expert_layer(monkeypatch, tmp_path):
    fetched = []
    monkeypatch.setattr(pubmed, "search", lambda q, retmax=8, as_of=None: ["1"])
    monkeypatch.setattr(pubmed, "fetch", lambda ids: (fetched.append(list(ids)), {"1": ABSTRACT})[1])
    monkeypatch.setattr(verifier, "drugage_records", lambda claim, allowed=None, cid=None: ([], []))
    path = _expert_file(tmp_path, [
        {"id": "e1", "by": "expert A", "at": "2026-10-20", "point": "evidence_conflict", "hypothesis": "H-0001",
         "target": "c1", "decision": "accept", "source": "PMID:23863708"},
        {"id": "e2", "by": "expert A", "at": "2026-10-20", "point": "objection", "target": "H-0002",
         "decision": "reject", "rationale": "no source: an opinion only"},
        {"id": "e3", "by": "expert A", "at": "2026-10-20", "point": "pairwise", "target": ["H-0001", "H-0002"],
         "decision": "prefer H-0002", "profile": "evidence_first"}],
        hypotheses=["The expert compound extends the lifespan of mice."])
    res = pipeline.run(["The fake compound extends the lifespan of mice.", "Another fake compound helps old mice."],
                       fake=True, K=2000, expert=path)
    assert [x["origin"] for x in res["items"]] == ["external", "external", "expert"]
    assert any("23863708" in ids for ids in fetched)                         # the expert's source went to the verifier
    h1, h2 = res["items"][0], res["items"][1]
    assert h1["expert"][0]["kind"] == "source sent to the verifier"
    assert h2["expert"][0]["kind"] == "expert opinion"
    ef = res["ranking"]["evidence_first"]
    assert ef["meta"]["profile_version"].endswith("+expert-1") and ef["meta"]["prefer"][0]["a"] == "H-0002"
    assert ef["meta"]["prefer"][0]["approximate"]       # the fake cards leave cost, time ... unknown (spec 6a, MVP)
    assert set(res["ranking_autonomous"]) == set(res["ranking"]) and not res["criterion_gap"]


def test_preferences_from_pairwise_decisions():
    from hyparena.card import expert as ex
    layer = ex.ExpertLayer.model_validate({"decisions": [
        {"id": "e1", "point": "pairwise", "target": ["H-1", "H-2"], "decision": "prefer H-2"},
        {"id": "e2", "point": "pairwise", "target": ["H-1", "H-3"], "decision": "prefer H-1", "profile": "fundamental"}]})
    prefs = ex.preferences(layer)
    assert [(c.a, c.b) for c in prefs[None]] == [("H-2", "H-1")] and prefs["fundamental"][0].a == "H-1"
    bad = ex.ExpertLayer.model_validate({"decisions": [
        {"id": "e3", "point": "pairwise", "target": ["H-1", "H-2"], "decision": "prefer H-9"}]})
    try:
        ex.preferences(bad)
        assert False
    except ValueError:
        pass


def test_ladder_result_orders_by_outcome():
    res = {"meta": {"families": ["google"], "calls": 3, "as_of": None},
           "calls": [{"kind": "llm", "tokens_in": 10, "tokens_out": 5}],
           "ranking": {"evidence_first": {"expected": {"H-0002": 0.4, "H-0003": 0.6}}},
           "items": [{"id": f"H-000{i}", "outcome": o, "card": None, "verification": None}
                     for i, o in enumerate(["filtered", "ranked", "ranked", "known_result", "needs_refinement"], 1)]}
    out = pipeline.as_ladder_result(res, ["a", "b", "c", "d", "e"])
    score = {h: v["combined"] for h, v in out["hypotheses"].items()}
    assert sorted(score, key=score.get, reverse=True) == ["d", "c", "b", "e", "a"]
    assert out["tokens"]["all"] == {"tokens_in": 10, "tokens_out": 5}


LOVAZA = {**ABSTRACT, "abstract": "Results show for the first time that 4% Lovaza significantly extends both the median "
          "and maximal life span of (NZBxNZW)F1 mice."}


def _lovaza_card(relation):
    from hyparena.card.models import HypothesisCard
    return HypothesisCard.model_validate({"id": "H-1", "hypothesis_type": "interventional", "claim_plain": "",
        "pico": {"population": {"label": "mouse"}, "intervention": [{"type": "compound", "label": "Lovaza"}],
                 "outcome": {"endpoint": "lifespan"}},
        "claims": [{"id": "c1", "subject": {"label": "Lovaza"}, "relation": relation, "object": {"label": "mouse"},
                    "qualifiers": {"species": "mouse"}, "role": "outcome", "source_span": "x"}]})


def test_lifespan_stance_comes_from_the_effect_direction(monkeypatch):
    card = _lovaza_card("shortens_lifespan_in")
    quote = "4% Lovaza significantly extends both the median and maximal life span of (NZBxNZW)F1 mice."
    _stub(monkeypatch, [_record(quote=quote, stance="supports", effect="increase", qualifiers_match={"species": "yes"})])
    monkeypatch.setattr(pubmed, "fetch", lambda ids: {"1": LOVAZA})
    cv = verifier.verify_claim(None, "google", frozenset(), card.claims[0], card)
    assert not cv.evidence and len(cv.counterevidence) == 1          # "extends" refutes "shortens", whatever the extractor said
    rec = cv.counterevidence[0]
    assert rec.effect == "increase" and "stance set from the effect direction" in rec.notes
    assert "disease_model" in rec.flags and "NZB/W F1" in rec.notes  # a lupus-prone strain named in the abstract


def test_effect_level_on_disease_models_only_is_noted(monkeypatch):
    from hyparena.card.models import Verification
    from hyparena.card.rules import finalize
    card = _lovaza_card("extends_lifespan_in")
    quote = "4% Lovaza significantly extends both the median and maximal life span of (NZBxNZW)F1 mice."
    _stub(monkeypatch, [_record(quote=quote, effect="increase", qualifiers_match={"species": "yes"})])
    monkeypatch.setattr(pubmed, "fetch", lambda ids: {"1": LOVAZA})
    cv = verifier.verify_claim(None, "google", frozenset(), card.claims[0], card)
    ver = finalize(card, Verification(card_id="H-1", claims=[cv]))
    assert ver.claims[0].status == "supported"                        # flags do not change a status (spec 7)
    assert ver.evidence_profile.effect_level_note == "mammals (disease models or special conditions only)"


def test_a_quote_about_another_compound_does_not_count(monkeypatch):
    card = _fixture_card("ex5_resveratrol_endpoint")
    other = {**ABSTRACT, "title": "Malate and fumarate extend lifespan in mice.", "abstract": "Malate increased lifespan in mice."}
    _stub(monkeypatch, [_record(quote="Malate increased lifespan in mice.", effect="increase", qualifiers_match={"species": "yes"})])
    monkeypatch.setattr(pubmed, "fetch", lambda ids: {"1": other})
    cv = verifier.verify_claim(None, "google", frozenset(), card.claims[0], card)
    rec = cv.evidence[0]
    assert rec.qualifiers_match["intervention_match"] == "related_compound"
    from hyparena.card.rules import claim_status
    assert claim_status(cv, card.claims[0]) == "unverified"          # related compounds count only as analogs


def test_a_combination_needs_every_component_named(monkeypatch):
    from hyparena.card import entities
    card = _fixture_card("ex2_senolytics_function")
    entities.resolve_card(card)
    c4 = card.claims[3]
    assert verifier.names_intervention(c4, card, "Dasatinib plus quercetin improved function")
    assert not verifier.names_intervention(c4, card, "Dasatinib alone improved function")
    assert verifier.names_intervention(c4, card, "Sprycel and sophoretin")           # synonyms

"""Alternatives (card spec 8c): declared rows, checklist inclusion rules, the one-call check."""
from hyparena.card import alternatives as al
from hyparena.card.models import EvidenceRecord, HypothesisCard, Verification
from hyparena.card.rules import finalize
from hyparena.tools import pubmed
from tests.test_card_rules import load


def _case(name):
    d = load(name)
    card = HypothesisCard.model_validate(d["card"])
    return card, finalize(card, Verification.model_validate(d["verification"]))


def types(ver):
    return [a.type for a in ver.alternatives if a.source == "checklist"]


def test_rows_of_the_examples():
    assert types(_case("ex1_rapamycin_healthspan")[1]) == ["dose_regimen"]    # ITP: one dose and start age
    assert types(_case("ex3_rapamycin_mechanism")[1]) == []                    # endpoint mechanism
    assert types(_case("ex5_resveratrol_endpoint")[1]) == ["food_intake", "body_temperature", "disease_specific"]
    assert [a.id for a in _case("ex5_resveratrol_endpoint")[1].alternatives] == ["alt1", "alt2", "alt3"]


def test_route_rules():
    card, ver = _case("ex5_resveratrol_endpoint")
    card.pico.intervention[0].route = "diet"
    t = types(finalize(card, ver))
    assert "microbes" in t and "exposure_failed" in t
    card.pico.intervention[0].type = "diet"                         # a diet: no hidden caloric restriction row
    assert "food_intake" not in types(finalize(card, ver))


def test_evidence_rules_sex_and_strain():
    card, ver = _case("ex2_senolytics_function")
    assert "sex_specific" in types(ver) and "genetic_background" not in types(ver)   # an1: sex not reported
    an1 = next(cv for cv in ver.claims if cv.id == "an1")
    an1.evidence[0].sex, an1.evidence[0].strain = "both", "C57BL/6"
    t = types(finalize(card, ver))
    assert "sex_specific" not in t and "genetic_background" in t                       # one inbred strain
    an1.evidence[0].strain = "UM-HET3"
    assert "genetic_background" not in types(finalize(card, ver))


def test_type_rules():
    card, ver = _case("ex2_senolytics_function")
    card.hypothesis_type = "observational"
    assert {"confounding", "reverse_causation"} <= set(types(finalize(card, ver)))
    card.hypothesis_type = "biomarker"
    assert {"age_proxy", "disease_proxy"} <= set(types(finalize(card, ver)))


def test_declared_row_carries_the_claim_status():
    _, ver = _case("ex3_rapamycin_mechanism")
    assert [(a.id, a.source, a.status) for a in ver.alternatives] == [("a1", "declared", "contested")]


ABSTRACT = {"pmid": "9", "year": "2015", "title": "Resveratrol and food intake.",
            "abstract": "Pair-fed controls did not differ. Lifespan was extended in resveratrol-treated mice relative to pair-fed controls."}


def _check(monkeypatch, reply):
    card, ver = _case("ex5_resveratrol_endpoint")
    ver.searched_pmids = ["9"]
    monkeypatch.setattr(pubmed, "fetch", lambda ids: {"9": ABSTRACT})
    monkeypatch.setattr(al, "ask", lambda *a, **k: (reply, "fake"))
    return card, al.check(None, "google", card, ver)


def test_check_marks_excluded_with_a_verbatim_quote(monkeypatch):
    q = "Lifespan was extended in resveratrol-treated mice relative to pair-fed controls."
    card, ver = _check(monkeypatch, {"alternatives": [{"id": "alt1", "found": "excluded", "pmid": "9", "quote": q},
                                                      {"id": "alt2", "found": "absent"}]})
    alt1, alt2 = ver.alternatives[:2]
    assert (alt1.status, alt1.record_id, alt1.quote) == ("excluded_by_evidence", "PMID:9", q)
    assert alt2.status == "open"
    assert finalize(card, ver).alternatives[0].status == "excluded_by_evidence"     # kept on recompute


def test_check_drops_a_quote_not_in_the_abstract(monkeypatch):
    _, ver = _check(monkeypatch, {"alternatives": [{"id": "alt1", "found": "excluded", "pmid": "9",
                                                    "quote": "food intake was matched"}]})
    assert ver.alternatives[0].status == "open"


def test_validate_names_the_problems():
    probs = al._validate({"alternatives": [{"id": "alt9"}, {"id": "alt1", "found": "supported", "pmid": "1", "quote": "x"}]},
                         {"alt1"}, {"9": ABSTRACT})
    assert len(probs) == 2

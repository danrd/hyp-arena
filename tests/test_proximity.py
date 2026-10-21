"""Typed proximity from the card (spec 8b): duplicate, variant, competitor, contradiction, analog,
mechanism neighbour."""
import time

from hyparena.card import proximity as px
from hyparena.card.entities import resolve_card
from hyparena.card.models import Claim, Entity, HypothesisCard
from tests.test_card_rules import load


def card(name="ex5_resveratrol_endpoint", cid="H-A"):
    c = HypothesisCard.model_validate({**load(name)["card"], "id": cid})
    resolve_card(c)
    return c


def mech(c, relation, obj, cid="m1", hallmark=None):
    c.claims.append(Claim(id=cid, subject=Entity(label=c.pico.intervention[0].label), relation=relation,
                          object=Entity(label=obj, hallmark=hallmark), role="mechanism", source_span="x"))
    return c


def types(a, b):
    r = px.relate(px.signature(a, px.compound_targets), px.signature(b, px.compound_targets))
    return r.types if r else []


def test_duplicate_and_variant():
    a, b = card(cid="H-A"), card(cid="H-B")
    assert types(a, b) == ["duplicate"]
    b.pico.population.age_at_start = "old"
    assert types(a, b) == ["variant"]
    r = px.relate(px.signature(a), px.signature(b))
    assert r.details["context_differs"] == ["age_at_start"]


def test_mechanism_in_one_only_is_a_variant_not_a_duplicate():
    a, b = card(cid="H-A"), mech(card(cid="H-B"), "activates", "SIRT1")
    assert types(a, b) == ["variant"]


def test_competitor_needs_different_mechanisms():
    a = mech(card(cid="H-A"), "activates", "SIRT1")
    b = mech(card(cid="H-B"), "suppresses", "inflammation")
    assert types(a, b) == ["competitor"]
    b.pico.population.sex = "male"
    assert types(a, b) == ["competitor", "variant"]
    assert types(a, mech(card(cid="H-C"), "activates", "SIRT1")) == ["duplicate"]


def test_contradiction_on_the_outcome_and_on_any_claim():
    a, b = card(cid="H-A"), card(cid="H-B")
    b.claims[0].relation = "no_lifespan_effect_in"
    assert types(a, b) == ["contradiction"]
    b = card(cid="H-B")
    b.claims[0].qualifiers["direction"] = "no_effect"                 # a negated "extends"
    assert types(a, b) == ["contradiction"]
    a, b = mech(card(cid="H-A"), "activates", "SIRT1"), mech(card(cid="H-B"), "inhibits", "SIRT1")
    r = px.relate(px.signature(a), px.signature(b))
    assert r.types == ["contradiction", "competitor"] and r.details["contradicting_claims"] == [("m1", "m1")]


def test_mechanistic_competitors_explain_the_same_effect_differently():
    a = card("ex3_rapamycin_mechanism", "H-A")                     # mainly via cancer, not via aging
    b = card("ex3_rapamycin_mechanism", "H-B")
    b.claims[1] = Claim(id="c2", subject=Entity(label="rapamycin"), relation="slows_aging_in",
                        object=Entity(label="mouse"), qualifiers={"species": "mouse"}, role="outcome", source_span="x")
    assert types(a, b) == ["competitor"]


def test_analog_by_shared_target():
    a = card("ex1_rapamycin_healthspan", "H-A")
    b = card("ex1_rapamycin_healthspan", "H-B")
    b.pico.intervention[0].label, b.pico.intervention[0].id = "everolimus", None
    for c in b.claims:
        c.subject = Entity(label="everolimus")
    resolve_card(b)
    r = px.relate(px.signature(a, px.compound_targets), px.signature(b, px.compound_targets))
    assert "analog" in r.types and r.details["shared_targets"] == ["CHEMBL1902"]
    assert "mechanism_neighbour" in r.types and "mtorc1" in r.details["shared_nodes"]   # both inhibit mTORC1


def test_mechanism_neighbour_by_hallmark():
    a = mech(card(cid="H-A"), "suppresses", "senescent cells", hallmark="cellular_senescence")
    b = mech(card("ex1_rapamycin_healthspan", "H-B"), "suppresses", "p16 cells", hallmark="cellular_senescence")
    r = px.relate(px.signature(a), px.signature(b))
    assert r.types == ["mechanism_neighbour"] and r.details["shared_nodes"] == ["cellular_senescence"]


def test_unrelated_examples():
    cards = [card(n, f"H-{i}") for i, n in enumerate(["ex1_rapamycin_healthspan", "ex2_senolytics_function",
                                                       "ex3_rapamycin_mechanism", "ex5_resveratrol_endpoint"])]
    assert px.relations(cards) == []          # rapamycin in humans and in mice: another species, no relation type


def test_groups_and_duplicates():
    a, b, c = card(cid="H-1"), card(cid="H-2"), card(cid="H-3")
    c.pico.population.sex = "male"
    rels = px.relations([a, b, c])
    assert px.duplicates(rels, ["H-1", "H-2", "H-3"]) == {"H-2": "H-1"}
    assert px.variant_groups(rels) == [["H-1", "H-2", "H-3"]]
    d = mech(card(cid="H-4"), "activates", "SIRT1")
    e = mech(card(cid="H-5"), "suppresses", "inflammation")
    assert px.competitors(px.relations([d, e])) == {"H-4": ["H-5"], "H-5": ["H-4"]}


def test_competitors_become_alternatives():
    from hyparena.card import alternatives
    from hyparena.card.models import Verification
    from hyparena.card.rules import finalize
    d = load("ex5_resveratrol_endpoint")
    a = card(cid="H-0006")
    rival = mech(card(cid="H-9"), "activates", "SIRT1")
    ver = Verification.model_validate(d["verification"])
    ver.alternatives = alternatives.competitor_rows([rival])
    ver = finalize(a, ver)
    rows = [(x.id, x.type, x.source, x.ref) for x in ver.alternatives]
    assert rows[-1] == ("alt4", "competitor", "proximity", "H-9")          # after three checklist rows
    assert [x.id for x in finalize(a, ver).alternatives] == ["alt1", "alt2", "alt3", "alt4"]   # stable


def test_many_cards_are_cheap():
    base = [card(cid=f"H-{i}") for i in range(300)]
    for i, c in enumerate(base):
        c.pico.intervention[0].label, c.pico.intervention[0].id = f"compound{i % 150}", None
        c.claims[0].subject = Entity(label=f"compound{i % 150}")
    t = time.time()
    rels = px.relations(base)
    assert time.time() - t < 5 and len(rels) == 150                       # 150 duplicate pairs

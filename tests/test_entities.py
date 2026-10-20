"""Compound identifiers in the card (offline table from conftest)."""
from pathlib import Path

import yaml

from hyparena.card import entities, sources
from hyparena.card.models import Claim, Entity, HypothesisCard
from hyparena.card.rules import same_intervention
from hyparena.tools import compounds as cp

FIX = Path(__file__).parent / "fixtures" / "cards"


def card(name):
    return HypothesisCard.model_validate(yaml.safe_load((FIX / f"{name}.yaml").read_text())["card"])


def test_combination_gets_ids_and_general_claims_do_not(monkeypatch):
    c = card("ex2_senolytics_function")
    assert entities.resolve_card(c) == []
    assert [i.id for i in c.pico.intervention] == ["CHEBI:49375", "CHEBI:16243"]
    by = {x.id: x for x in c.claims}
    assert by["c4"].subject.id == "CHEBI:16243+CHEBI:49375"      # "dasatinib + quercetin"
    assert by["c3"].subject.id is None                            # "senescent cells / SASP": not the intervention
    assert same_intervention(by["c4"], c)


def test_sasp_is_never_looked_up_as_a_subject(monkeypatch):
    asked = []
    real = cp.lookup
    monkeypatch.setattr(cp, "lookup", lambda name: (asked.append(name), real(name))[1])
    entities.resolve_card(card("ex2_senolytics_function"))
    assert set(asked) == {"dasatinib", "quercetin"}


def test_synonym_is_the_same_intervention():
    c = card("ex1_rapamycin_healthspan")
    entities.resolve_card(c)
    claim = Claim(id="x", subject=Entity(label="sirolimus"), relation="extends_lifespan_in",
                  object=Entity(label="mouse"), role="analog")
    c.claims.append(claim)
    entities.resolve_card(c)
    assert claim.subject.id == "CHEBI:9168" and same_intervention(claim, c)


def test_unresolved_class_falls_back_to_names():
    c = card("ex1_rapamycin_healthspan")
    c.pico.intervention[0].label = "senolytics"
    c.pico.intervention[0].id = None
    assert entities.resolve_card(c) == ["senolytics"]
    assert entities.max_phase(c) is None


def test_phase_of_a_combination_is_its_least_advanced_part():
    c = card("ex2_senolytics_function")
    assert entities.max_phase(c) == 3


def test_drugage_matches_by_compound(monkeypatch):
    row = {"compound_name": "Sirolimus", "species": "Mus musculus", "pubmed_id": "1", "avg_lifespan_significance": "S",
           "avg_lifespan_change_percent": "10", "max_lifespan_significance": "", "max_lifespan_change_percent": "",
           "gender": "male", "ITP": "", "dosage": "14 ppm"}
    monkeypatch.setattr(sources, "_rows", lambda: [row])
    monkeypatch.setattr(sources, "drugage_map", lambda: {"sirolimus": 5284616})
    claim = Claim(id="c", subject=Entity(label="rapamycin"), relation="extends_lifespan_in",
                  object=Entity(label="mouse"), role="outcome")
    assert sources.drugage_records(claim)[0] == []                              # by name: no match
    assert len(sources.drugage_records(claim, cid=5284616)[0]) == 1             # by compound: the same drug


def test_key_folds_unicode_dashes():
    assert cp.key("17‐alpha‐estradiol") == cp.key("17-alpha-estradiol")


def test_active_metals_keep_their_own_compound():
    keep = ["Zinc acetate", "Cupric gluconate", "Lithium Chloride", "Sodium Chloride", "Magnesium chloride"]
    collapse = ["Dexamethasone sodium phosphate", "Calcium pantothenate", "Sodium pyruvate", "Doxycycline hydrochloride"]
    assert all(cp.keeps_own_compound(n) for n in keep)
    assert not any(cp.keeps_own_compound(n) for n in collapse)

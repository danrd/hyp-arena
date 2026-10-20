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


def test_drugage_paper_category_decides_every_lifespan_relation(monkeypatch):
    ns = {"compound_name": "Procaine HCl", "species": "Drosophila melanogaster", "pubmed_id": "4397875",
          "avg_lifespan_significance": "NS", "avg_lifespan_change_percent": "2", "max_lifespan_significance": "",
          "max_lifespan_change_percent": "", "gender": "male", "ITP": "", "dosage": "1 mg"}
    monkeypatch.setattr(sources, "_rows", lambda: [ns])
    monkeypatch.setattr(sources, "drugage_map", lambda: {})

    def claim(relation, **q):
        return Claim(id="c", subject=Entity(label="Procaine HCl"), relation=relation, object=Entity(label="fly"),
                     qualifiers=q, role="outcome")
    counts = lambda c: tuple(len(x) for x in sources.drugage_records(c))
    assert counts(claim("extends_lifespan_in")) == (0, 1)
    assert counts(claim("shortens_lifespan_in")) == (0, 1)       # no effect refutes "shortens" too
    assert counts(claim("no_lifespan_effect_in")) == (1, 0)
    assert counts(claim("extends_lifespan_in", direction="no_effect")) == (1, 0)   # a negated claim


def test_drugage_strain_flags_a_disease_model(monkeypatch):
    row = {"compound_name": "Rapamycin", "species": "Mus musculus", "strain": "AKR", "pubmed_id": "2",
           "avg_lifespan_significance": "S", "avg_lifespan_change_percent": "12", "max_lifespan_significance": "",
           "max_lifespan_change_percent": "", "gender": "female", "ITP": "", "dosage": "x"}
    monkeypatch.setattr(sources, "_rows", lambda: [row])
    monkeypatch.setattr(sources, "drugage_map", lambda: {})
    claim = Claim(id="c", subject=Entity(label="Rapamycin"), relation="extends_lifespan_in",
                  object=Entity(label="mouse"), role="outcome")
    rec = sources.drugage_records(claim)[0][0]
    assert "disease_model" in rec.flags and "AKR" in rec.notes and rec.effect == "increase"


def _rapa_row(**kw):
    return {"compound_name": "Rapamycin", "species": "Mus musculus", "strain": "UM-HET3", "pubmed_id": "19587680",
            "avg_lifespan_significance": "S", "avg_lifespan_change_percent": "13", "max_lifespan_significance": "",
            "max_lifespan_change_percent": "", "gender": "Female", "ITP": "Yes", "dosage": "14 ppm food",
            "age_at_initiation": "20 months", **kw}


def test_drugage_record_fields_and_one_record_per_strain(monkeypatch):
    rows = [_rapa_row(), _rapa_row(gender="Male", avg_lifespan_change_percent="9"),
            _rapa_row(strain="C57BL/6", avg_lifespan_significance="NS", avg_lifespan_change_percent="1")]
    monkeypatch.setattr(sources, "_rows", lambda: rows)
    monkeypatch.setattr(sources, "drugage_map", lambda: {})
    claim = Claim(id="c", subject=Entity(label="Rapamycin"), relation="extends_lifespan_in",
                  object=Entity(label="mouse"), role="outcome")
    support, against = sources.drugage_records(claim)
    assert [(r.strain, r.sex) for r in support] == [("UM-HET3", "both")]
    assert [(r.strain, r.sex) for r in against] == [("C57BL/6", "female")]
    assert support[0].dose == "14 ppm food" and support[0].age_at_start == "20 months"
    assert support[0].record_id.endswith("PMID19587680/UM-HET3")


def test_curated_intervention_match_by_route_and_regimen(monkeypatch):
    from tests.test_card_rules import load
    from hyparena.card.models import EvidenceRecord, HypothesisCard
    card = HypothesisCard.model_validate(load("ex1_rapamycin_healthspan")["card"])     # weekly, intermittent
    rec = EvidenceRecord(source="DrugAge", record_id="x", epistemic_type="B_curated", dose="14 ppm food")
    assert sources.curated_intervention_match(card, rec) == "regimen_differs"
    card.pico.intervention[0].regimen, card.pico.intervention[0].route = "unknown", "diet"
    assert sources.curated_intervention_match(card, rec) == "exact"
    card.pico.intervention[0].route = "water"
    assert sources.curated_intervention_match(card, rec) == "regimen_differs"
    rec.dose = "2 mg/kg"                                                               # route not stated: no grade
    assert sources.curated_intervention_match(card, rec) == "exact"

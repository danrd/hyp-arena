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
    assert entities.human_safety(c) is None


def test_human_safety_today_and_as_of_t():
    c = card("ex1_rapamycin_healthspan")                       # approved 1999, first trial 1989
    assert entities.human_safety(c) is True
    assert entities.human_safety(c, "2000-01-01") is True        # approved by then
    assert entities.human_safety(c, "1995-01-01") is True        # clinical stage: a trial started before T
    assert entities.human_safety(c, "1985-01-01") is False


def test_human_safety_of_a_combination_needs_every_part():
    c = card("ex2_senolytics_function")                        # dasatinib trial 2003-11, quercetin 2004-02
    assert entities.human_safety(c) is True
    assert entities.human_safety(c, "2004-06-01") is True
    assert entities.human_safety(c, "2004-01-01") is False


def test_diet_has_human_safety_data_and_a_gene_is_unknown():
    c = card("ex1_rapamycin_healthspan")
    c.pico.intervention[0].type, c.pico.intervention[0].label = "diet", "caloric restriction"
    assert entities.human_safety(c, "1950-01-01") is True
    c.pico.intervention[0].type, c.pico.intervention[0].label = "gene", "PAPPA knockout"
    assert entities.human_safety(c) is None


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


def test_real_lookup_reads_the_cache_and_upgrades_old_entries(monkeypatch, tmp_path):
    """The real cp.lookup, not the offline stand-in: a name missing from the cache must not crash (it did once:
    the "missing" marker was read as an entry), and an entry from an older fetch is completed once."""
    import json
    from tests.conftest import REAL_LOOKUP
    current = {"cid": 1, "name": "Done", "chembl": "CHEMBL1", "first_approval": None, "targets": ["T1"], "atc": [],
               "chembl_rev": cp.CHEMBL_REV}
    old = {"cid": 2, "name": "Old", "chembl": "CHEMBL2", "max_phase": 4, "targets": []}      # before first_approval / rev 2
    monkeypatch.setattr(cp, "CACHE", tmp_path / "compounds.json")
    monkeypatch.setattr(cp, "_cache", {"done": current, "notacompound": None, "old": old})
    calls = []

    def fake_get(url):
        calls.append(url)
        if "mechanism.json" in url:
            return {"mechanisms": [{"target_chembl_id": "CHEMBL1902"}]}
        if "molecule_form.json" in url:
            return {"molecule_forms": [{"molecule_chembl_id": "CHEMBL2"}, {"molecule_chembl_id": "CHEMBL22"}]}
        if "atc_classifications" in url:
            return {"atc_classifications": ["L04AH01"] if "CHEMBL22" in url else []}
        return {"molecule_chembl_id": "CHEMBL2", "max_phase": "4.0", "first_approval": 1999}
    monkeypatch.setattr(cp, "_get", fake_get)

    def no_network(name):
        raise cp.LookupError_(name)
    monkeypatch.setattr(cp, "parent_cid", no_network)
    assert REAL_LOOKUP("Done").targets == ["T1"] and calls == []             # current entry: no network
    assert REAL_LOOKUP("notacompound") is None and calls == []                # cached "not found"
    assert REAL_LOOKUP("never seen") is None                                  # not in the cache, network down
    up = REAL_LOOKUP("old")
    assert (up.first_approval, up.targets, up.atc, up.chembl_rev) == (1999, ["CHEMBL1902"], ["L04AH01"], cp.CHEMBL_REV)
    assert json.loads((tmp_path / "compounds.json").read_text())["old"]["chembl_rev"] == cp.CHEMBL_REV

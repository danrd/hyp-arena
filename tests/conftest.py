"""Tests never look compounds up on the network: offline tables stand in for PubChem, ChEMBL and ClinicalTrials.gov."""
import pytest

from hyparena.tools import chebi, compounds as cp, trials

REAL_LOOKUP = cp.lookup          # the unpatched function, for tests of the cache itself (tests/test_entities.py)

OFFLINE = {
    "rapamycin": cp.Compound(5284616, "Sirolimus", chebi="CHEBI:9168", chembl="CHEMBL413", max_phase=4, first_approval=1999,
                             targets=["CHEMBL1902"], atc=["L01EG04", "L04AH01", "S01XA23"], chembl_rev=2,
                             synonyms=["rapamycin", "Sirolimus", "Rapamune"]),
    "dasatinib": cp.Compound(3062316, "Dasatinib", chebi="CHEBI:49375", chembl="CHEMBL1421", max_phase=4, first_approval=2006,
                             synonyms=["dasatinib", "Sprycel"]),
    "quercetin": cp.Compound(5280343, "Quercetin", chebi="CHEBI:16243", chembl="CHEMBL50", max_phase=3,
                             synonyms=["quercetin", "Sophoretin"]),
    "resveratrol": cp.Compound(445154, "Resveratrol", chebi="CHEBI:27881", chembl="CHEMBL165", max_phase=3,
                               synonyms=["resveratrol"]),
    "everolimus": cp.Compound(6442177, "Everolimus", chebi="CHEBI:68478", chembl="CHEMBL1908360", max_phase=4,
                              first_approval=2009, targets=["CHEMBL1902"], atc=["L01EG02", "L04AH02"], chembl_rev=2,
                              synonyms=["everolimus", "RAD001"]),
    # FKBP1A binders that inhibit calcineurin, not mTOR (spec 8b): not analogs of sirolimus
    "tacrolimus": cp.Compound(445643, "Tacrolimus", chebi="CHEBI:61049", chembl="CHEMBL269732", max_phase=4, first_approval=1994,
                              targets=["CHEMBL1902"], atc=["D11AH01", "L04AD02"], chembl_rev=2, synonyms=["tacrolimus"]),
    "pimecrolimus": cp.Compound(6509979, "Pimecrolimus", chembl="CHEMBL1200686", max_phase=4, targets=["CHEMBL1902"],
                                atc=["D11AH02"], chembl_rev=2, synonyms=["pimecrolimus"]),
    "temsirolimus": cp.Compound(6918289, "Temsirolimus", chembl="CHEMBL1201182", max_phase=4, targets=["CHEMBL1902"],
                                atc=["L01EG01"], chembl_rev=2, synonyms=["temsirolimus"]),
    "fkbpbinderx": cp.Compound(2, "FKBP binder X", chembl="CHEMBL2", max_phase=1, targets=["CHEMBL1902"], atc=[],
                               chembl_rev=2, synonyms=["fkbp binder x"]),
    "fisetin": cp.Compound(5281614, "Fisetin", chebi="CHEBI:42567", chembl="CHEMBL31574", max_phase=2, targets=[],
                           synonyms=["fisetin"]),
    "fakecompound": cp.Compound(1, "Fake compound", chembl="CHEMBL1", max_phase=2, synonyms=["fake compound"]),
}
OFFLINE["sirolimus"] = OFFLINE["rapamycin"]


TRIALS = {"sirolimus": "1989-09-15", "dasatinib": "2003-11", "quercetin": "2004-02", "resveratrol": "2007-01",
          "fake compound": ""}


CHEBI_CLASSES = {      # narrow is_a ancestors (id, label, size), from OLS4 on 2026-10-21
    "CHEBI:9168": [("CHEBI:145565", "macrolide lactam", 10)], "CHEBI:68478": [("CHEBI:145565", "macrolide lactam", 10)],
    "CHEBI:61049": [("CHEBI:145565", "macrolide lactam", 10)],
    "CHEBI:16243": [("CHEBI:52267", "7-hydroxyflavonol", 41)],
    "CHEBI:42567": [("CHEBI:52267", "7-hydroxyflavonol", 41)],
    "CHEBI:27881": [("CHEBI:36027", "stilbenol", 30)]}


@pytest.fixture(autouse=True)
def offline_compounds(monkeypatch):
    monkeypatch.setenv("HYPARENA_EMBEDDER", "none")             # no model download in tests
    monkeypatch.setattr(chebi, "classes", lambda cid, max_descendants=50: [c for c in CHEBI_CLASSES.get(cid, []) if c[2] <= max_descendants])
    monkeypatch.setattr(cp, "lookup", lambda name: OFFLINE.get(cp.key(name)))
    monkeypatch.setattr(trials, "first_trial_start", lambda name: TRIALS.get(name.strip().lower(), ""))

"""Tests never look compounds up on the network: offline tables stand in for PubChem, ChEMBL and ClinicalTrials.gov."""
import pytest

from hyparena.tools import compounds as cp, trials

OFFLINE = {
    "rapamycin": cp.Compound(5284616, "Sirolimus", chebi="CHEBI:9168", chembl="CHEMBL413", max_phase=4, first_approval=1999,
                             targets=["CHEMBL1902"],
                             synonyms=["rapamycin", "Sirolimus", "Rapamune"]),
    "dasatinib": cp.Compound(3062316, "Dasatinib", chebi="CHEBI:49375", chembl="CHEMBL1421", max_phase=4, first_approval=2006,
                             synonyms=["dasatinib", "Sprycel"]),
    "quercetin": cp.Compound(5280343, "Quercetin", chebi="CHEBI:16243", chembl="CHEMBL50", max_phase=3,
                             synonyms=["quercetin", "Sophoretin"]),
    "resveratrol": cp.Compound(445154, "Resveratrol", chebi="CHEBI:27881", chembl="CHEMBL165", max_phase=3,
                               synonyms=["resveratrol"]),
    "everolimus": cp.Compound(6442177, "Everolimus", chebi="CHEBI:68478", chembl="CHEMBL1908360", max_phase=4,
                              first_approval=2009, targets=["CHEMBL1902"], synonyms=["everolimus", "RAD001"]),
    "fakecompound": cp.Compound(1, "Fake compound", chembl="CHEMBL1", max_phase=2, synonyms=["fake compound"]),
}
OFFLINE["sirolimus"] = OFFLINE["rapamycin"]


TRIALS = {"sirolimus": "1989-09-15", "dasatinib": "2003-11", "quercetin": "2004-02", "resveratrol": "2007-01",
          "fake compound": ""}


@pytest.fixture(autouse=True)
def offline_compounds(monkeypatch):
    monkeypatch.setattr(cp, "lookup", lambda name: OFFLINE.get(cp.key(name)))
    monkeypatch.setattr(trials, "first_trial_start", lambda name: TRIALS.get(name.strip().lower(), ""))

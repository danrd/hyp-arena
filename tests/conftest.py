"""Tests never look compounds up on the network: an offline table stands in for PubChem and ChEMBL."""
import pytest

from hyparena.tools import compounds as cp

OFFLINE = {
    "rapamycin": cp.Compound(5284616, "Sirolimus", chebi="CHEBI:9168", chembl="CHEMBL413", max_phase=4,
                             synonyms=["rapamycin", "Sirolimus", "Rapamune"]),
    "dasatinib": cp.Compound(3062316, "Dasatinib", chebi="CHEBI:49375", chembl="CHEMBL1421", max_phase=4,
                             synonyms=["dasatinib", "Sprycel"]),
    "quercetin": cp.Compound(5280343, "Quercetin", chebi="CHEBI:16243", chembl="CHEMBL50", max_phase=3,
                             synonyms=["quercetin", "Sophoretin"]),
    "resveratrol": cp.Compound(445154, "Resveratrol", chebi="CHEBI:27881", chembl="CHEMBL165", max_phase=3,
                               synonyms=["resveratrol"]),
    "fakecompound": cp.Compound(1, "Fake compound", chembl="CHEMBL1", max_phase=2, synonyms=["fake compound"]),
}
OFFLINE["sirolimus"] = OFFLINE["rapamycin"]


@pytest.fixture(autouse=True)
def offline_compounds(monkeypatch):
    monkeypatch.setattr(cp, "lookup", lambda name: OFFLINE.get(cp.key(name)))

"""MeSH identifiers by code: exact descriptor or entry term only (offline: the cache is filled by the test)."""
from hyparena.tools import mesh


def test_lookup_uses_the_cache_and_exact_terms(monkeypatch):
    monkeypatch.setattr(mesh, "_cache", {"sarcopenia": {"ui": "D055948", "name": "Sarcopenia", "trees": ["C10.597.613.612.500"],
                                                        "entry_terms": ["Sarcopenia", "Sarcopenias"]},
                                         "resistance training": {"ui": "D055070", "name": "Resistance Training",
                                                                 "trees": ["E02.760.169.063.500.387.875"],
                                                                 "entry_terms": ["Resistance Training", "Strength Training",
                                                                                 "Weight-Lifting Strengthening Program"]},
                                         "squat exercise": {}})
    monkeypatch.setattr(mesh, "_save", lambda: None)
    monkeypatch.setattr(mesh, "_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network in tests")))
    assert mesh.lookup("Sarcopenia")["ui"] == "D055948"
    assert mesh.lookup("squat exercise") is None                       # "not found" is cached too
    assert mesh.topic("sarcopenia")["name"] == "Sarcopenia"            # a disease (C)
    assert mesh.topic("resistance training") is None                   # a procedure (E) is not a topic
    assert mesh.synonyms("resistance training")[:2] == ["Resistance Training", "Strength Training"]

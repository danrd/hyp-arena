from hyparena import analyze
from hyparena.card import rules_v3 as r3
from hyparena.card.models import ClaimVerification
from tests.test_rules_v3 import card, claim, rec


def _case():
    c = card([claim("c1", "x", "activates", "AMPK", "engagement"),
              claim("c2", "AMPK", "suppresses", "senescent cells", "pathway", hallmark="cellular_senescence"),
              claim("c3", "x", "improves_healthspan_in", "human", "outcome", "outcome")],
             [{"id": "p1", "subject": {"label": "exercise"}, "relation": "other", "object": {"label": "function"},
               "support_pmids": ["9"], "on_positive": "eliminated", "on_negative": "unchanged"}])
    cvs = [ClaimVerification(id="c1", evidence=[rec(1, "animal", n=40, effect="large"), rec(2, "animal", n=40, effect="large")]),
           ClaimVerification(id="c3", evidence=[rec(3, "rct", n=120)])]
    alts = {"p1": ClaimVerification(id="p1", evidence=[rec(9, "observational", n=300)])}
    return c, cvs, alts


def test_report_explains_the_scores_and_points_at_the_weakest_link(monkeypatch):
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    c, cvs, alts = _case()
    rep = analyze.build(c, cvs, alts, variant="v3.1", unit="U1", pool={"U1": 0.0, "U2": 1.0})
    res = r3.evaluate(c, cvs, alts, variant="v3.1")
    assert rep["summary"]["V"] == res.V and rep["summary"]["rank"] == {"place": 2, "of": 2}
    assert [r["id"] for r in rep["chain"]] == ["c1", "c2", "c3"]
    assert rep["chain"][0]["records"][0]["pmid"] in ("1", "2")
    assert any("weakest link is c2" in w for w in rep["why"])
    gain = rep["improve"][0]
    assert "c2" in gain["action"] and gain["V_if_done"] > res.V
    md = analyze.markdown(rep)
    for h in ("## 1. Summary", "## 2. Mechanism chain", "## 3. Why this score", "## 4. What to improve", "## 5. Limitations",
              "## 6. Provenance"):
        assert h in md

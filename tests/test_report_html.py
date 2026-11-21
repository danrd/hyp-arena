import math

import pytest

from hyparena.reports import report_html as rh
from hyparena.novelty import novelty_v34 as nv
from hyparena.scoring import rules_v3 as r3, rules_v32 as r32
from tests.test_analyze import _case


def test_p_product_reproduces_the_rules(monkeypatch):
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    c, cvs, alts = _case()
    e = r32.evaluate(c, cvs, alts, fold=True)
    S = {k: v[0] for k, v in e.links.items()}
    assert rh.p_product(c, S) == pytest.approx(e.P, rel=1e-3)
    assert rh.p_product(c, {**S, "c2": 5 / 6}) > e.P


def test_contributions_use_rank_order_centroid_weights():
    w = rh.roc_weights([["P"], ["I"], ["W", "x"]])
    assert w["P"] > w["I"] > w["W"] == w["x"] and sum(w.values()) == pytest.approx(1.0)
    assert rh.percentiles({"a": 1.0, "b": 2.0, "c": None}) == {"a": 0.25, "b": 0.75, "c": None}


def test_weight_display_reproduces_the_score_and_marks_repeated_sources():
    card, verifications, _ = _case()
    claim = next(c for c in r3.chain(card) if c.id == "c3")
    verification = next(c for c in verifications if c.id == claim.id)
    record = verification.evidence[0].model_copy(update={
        "n_quote": "sixty participants", "qualifiers_match": {"intervention_match": "class"},
    })
    verification.evidence = [record, record.model_copy()]
    rows = rh._weighted_records(verification, claim)
    assert rows[0]["f"]["context"][1] == r32.CLASS_WEIGHT
    assert rows[0]["raw_weight"] == math.prod(value for _, value in rows[0]["f"].values())
    assert rows[0]["raw_weight"] == r32.current_weight(record, claim, False)
    assert rows[0]["weight_quotes"]["precision"]["text"] == "sixty participants"
    assert [r["fold"] for r in rows] == [1, r32.FOLD_REST]


def test_link_novelty_uses_the_record_that_sets_the_level():
    card, cvs, _ = _case()
    claim = next(c for c in r3.chain(card) if c.id == "c3")
    cv = next(v for v in cvs if v.id == claim.id)
    analog = cv.evidence[0].model_copy(update={"qualifiers_match": {"intervention_match": "class"}})
    transfer = analog.model_copy(update={"record_id": "PMID:4", "species": "mouse", "design": "animal",
                                         "qualifiers_match": {"species": "no", "intervention_match": "exact"}})
    cv.evidence = [analog]
    level, basis = nv.link_basis(claim, cv)
    assert level == "analog"
    assert rh._link_novelty_basis(basis, claim)["intervention_match"] == "class"

    cv.counterevidence = [transfer]
    level, basis = nv.link_basis(claim, cv)
    assert level == nv.link_level(claim, cv) == "translation"
    assert basis is transfer
    details = rh._link_novelty_basis(basis, claim)
    assert (details["pmid"], details["from_species"], details["to_species"]) == ("4", "mouse", "human")


def test_report_v2_renders_an_empty_pool_and_keeps_the_template_hooks():
    from hyparena.reports import report_v2 as r2
    from hyparena.scoring import aspid_v3
    tpl = r2.TEMPLATE.read_text()
    for hook in ("__DATA__", "__TITLE__", 'id="rank-body"', 'id="cards"', 'id="evals"', 'id="scheme"', 'id="glossary"', 'id="tt"'):
        assert hook in tpl
    assert "Топ-1" not in tpl and "top-3" not in tpl.lower()
    # manual section 10 (2026-11-11): five tabs, ranks of importance, no internal profile codes
    for tab in ("Рейтинг", "Карточки гипотез", "Оценка гипотез", "Схема работы", "Справка"):
        assert f">{tab}</button>" in tpl
    assert "ранг важности" in tpl and "trial-" not in tpl
    rep = {"meta": {"title_ru": "Пул", "title_en": "Pool", "about_ru": "", "about_en": "", "date": "2026-11-06", "method": "v3.4",
                    "sha": "0" * 64, "n": 0, "n_scored": 0, "outcomes": {}}, "hyps": {}, "ranks": {p: [] for p in aspid_v3.load()}}
    html = r2.render(rep)
    assert "__DATA__" not in html and '"profiles"' in html and "Фронтир" in html
    d = r2.data(rep)
    assert {g["term"] for g in d["glossary"]} >= {"запас улучшения", "новизна", "баланс доказательств", "сдвиг к известному"}
    assert "неопровергнутость механизма" not in {g["term"] for g in d["glossary"]}
    assert all("tier_keys" in p for p in d["profiles"]) and "relation" in d["names"]
    assert r2.slot_coverage([{"type": "engagement", "checked": True}, {"type": "pathway", "checked": False},
                             {"type": "pathway", "checked": True}, {"type": "outcome", "checked": False, "primary": True}]) == [2, 3]


def test_report_v2_passes_feasibility_breakdown_and_renders_tooltips():
    from hyparena.reports import report_v2 as r2
    from hyparena.scoring import aspid_v3
    tpl = r2.TEMPLATE.read_text(encoding="utf-8")
    assert "feasibilityBlock" in tpl and "Из чего складывается реализуемость" in tpl and "FEAS_TIPS" in tpl
    fb = {
        "score": 0.458,
        "denominator": 4,
        "parts": [
            {"key": "system", "value": "human", "score": 0.0, "in_denominator": True},
            {"key": "duration", "value": "months", "score": 0.667, "in_denominator": True},
            {"key": "sample_size", "value": 80, "score": 0.667, "in_denominator": True, "reason": "stated"},
            {"key": "readiness", "value": "clinical", "score": 0.5, "known": True, "in_denominator": True, "reason": "clinical"},
        ],
    }
    profs = list(aspid_v3.load())
    rep = {
        "meta": {"title_ru": "Пул", "title_en": "Pool", "about_ru": "", "about_en": "", "date": "2026-11-21",
                 "method": "v3.12", "sha": "0" * 64, "n": 1, "n_scored": 1, "outcomes": {}},
        "ranks": {p: ["h1"] for p in profs},
        "hyps": {
            "h1": {
                "title": "H1", "type": "compound", "P": 0.7, "gate": "pass", "I": 0.5, "scope": "organ",
                "N": "new_context", "chain": [], "alternatives": [], "values": {"feasibility": 0.458, "chain_state": 0.2},
                "feasibility_breakdown": fb,
                "contrib": {p: {"up": [], "down": []} for p in profs},
                "pct": {}, "aspid": {p: 0.5 for p in profs}, "rank": {p: 1 for p in profs}, "p_top5": {p: 1.0 for p in profs},
            }
        },
    }
    d = r2.data(rep)
    assert d["results"][0]["feasibility_breakdown"] == fb
    html = r2.render(rep)
    assert '"feasibility_breakdown"' in html

import pytest

from hyparena import report_html as rh
from hyparena.card import rules_v3 as r3, rules_v32 as r32
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


def test_report_v2_renders_an_empty_pool_and_keeps_the_template_hooks():
    from hyparena import report_v2 as r2
    from hyparena.card import aspid_v3
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

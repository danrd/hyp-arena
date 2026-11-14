"""Search mode "filtered" (hyparena/card/search.py, retrieve_filtered; search benchmark 2026-11-14)."""
from hyparena.card import rank, search
from hyparena.card.models import HypothesisCard


def test_select_threes_then_fill_with_twos_capped():
    order = [f"p{i}" for i in range(40)]
    scores = {p: 2 for p in order}
    for p in order[5:8]:
        scores[p] = 3
    got = rank.select(order, scores)
    assert got[:3] == ["p5", "p6", "p7"] and len(got) == 10 and got[3:] == ["p0", "p1", "p2", "p3", "p4", "p8", "p9"]
    many = {p: 3 for p in order}
    assert len(rank.select(order, many)) == 20                       # cap 20
    assert rank.select(order, {p: 1 for p in order}) == []           # nothing rated 2 or 3: nothing read


def test_bm25_orders_by_query_words():
    docs = {"a": rank.tokens("squat exercise improves physical performance in older adults"),
            "b": rank.tokens("cardiac surgery outcomes"), "c": rank.tokens("squat training")}
    assert rank.bm25(rank.query_terms(['("squat exercise"[tiab]) AND (physical performance[tiab])']), docs)[0] == "a"


def test_retrieve_filtered_reads_the_rated(monkeypatch):
    from hyparena.llm.fake import FakeLLMClient as FakeClient
    from hyparena.tools import pubmed
    card = HypothesisCard.model_validate({"id": "T", "hypothesis_type": "interventional", "claim_plain": "squats help",
                                          "pico": {"intervention": [{"label": "squat exercise"}]},
                                          "claims": [{"id": "c1", "subject": {"label": "squat exercise"}, "relation": "promotes",
                                                      "object": {"label": "physical performance"}, "source_span": "x",
                                                      "role": "outcome"}]})
    ids = [str(10000 + i) for i in range(60)]
    monkeypatch.setattr(search, "model_queries", lambda *a, **k: ["squat[tiab]"])
    monkeypatch.setattr(search, "_dated", lambda p, as_of: list(p))
    monkeypatch.setattr(search, "_links", lambda p, n: [])
    monkeypatch.setattr(pubmed, "search", lambda q, retmax=8, as_of=None: ids[:retmax])
    monkeypatch.setattr(pubmed, "fetch", lambda p: {x: {"title": f"squat study {x}", "abstract": "squat exercise", "year": "2010"} for x in p})
    log: list = []
    got = search.retrieve_filtered(FakeClient(seed=1), "google", frozenset(), card.claims[0], card, "2020-01-01", log=log)
    assert 0 < len(got) <= 20 and set(got) <= set(ids)
    f = [x for x in log if x.get("kind") == "search_filter"][0]
    assert f["candidates"] == 60 and f["rated"] == 60 and f["selected"] == got

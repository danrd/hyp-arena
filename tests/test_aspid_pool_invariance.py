"""ASPID pool invariance tests: duplicates and dominated hypotheses."""
import math
import random
import pytest
import numpy as np

from hyparena.aspid import aggregate, IndicatorSpec
from hyparena.card import pipeline, verifier
from hyparena.tools import pubmed
from hyparena.llm.fake import FakeLLMClient
import json
import re

ABSTRACT = {"abstract": "Fake abstract", "year": "2024", "title": "Fake title"}


def test_copies_do_not_affect_ranking_of_others(monkeypatch):
    """
    Copies are collapsed before aggregation.
    Build a result with exact copies of one hypothesis.
    Check that the copies are marked as duplicates and not in the ranking,
    and that the ranking (expected, p_topk, p_best, places) of the other hypotheses
    is identical to the run without the copies.
    """
    monkeypatch.setattr(pubmed, "search", lambda q, retmax=8, as_of=None: ["1"])
    monkeypatch.setattr(pubmed, "fetch", lambda ids: {"1": ABSTRACT})
    monkeypatch.setattr(verifier, "drugage_records", lambda claim, allowed=None, cid=None: ([], []))

    original_normalize = FakeLLMClient._normalize_card
    def custom_normalize(self, rng, prompt, n):
        m = re.search(r"<<<TEXT\n(.*?)\nTEXT>>>", prompt, flags=re.S)
        text = (m.group(1) if m else "a fake hypothesis").strip()
        span = text[:min(len(text), 50)]
        label = span
        return json.dumps({"hypothesis_type": "interventional", "claim_plain": span,
                           "pico": {"population": {"label": "mouse", "taxon": "NCBITaxon:10090"},
                                    "intervention": [{"type": "compound", "label": label, "regimen": "unknown"}],
                                    "outcome": {"endpoint": "lifespan", "metric": "unknown"}},
                           "claims": [{"id": "c1", "subject": {"label": label}, "relation": "extends_lifespan_in",
                                       "object": {"label": "mouse"}, "role": "outcome", "source_span": span}],
                           "edges": [], "decisive_experiment": {"system": "mouse", "endpoint": "lifespan", "duration_class": "years"}})
    monkeypatch.setattr(FakeLLMClient, "_normalize_card", custom_normalize)

    texts_base = [
        "A extends lifespan",
        "B extends lifespan",
        "C extends lifespan"
    ]

    texts_copies = [
        "A extends lifespan",
        "A extends lifespan",
        "A extends lifespan",
        "B extends lifespan",
        "C extends lifespan"
    ]

    res_base = pipeline.run(texts_base, fake=True, K=2000)
    res_copies = pipeline.run(texts_copies, fake=True, K=2000)

    outcomes = [x["outcome"] for x in res_copies["items"]]
    assert outcomes == ["ranked", "duplicate", "duplicate", "ranked", "ranked"]

    duplicates = [x["id"] for x in res_copies["items"] if x["outcome"] == "duplicate"]
    assert len(duplicates) == 2
    for dup in duplicates:
        assert dup not in res_copies["ranking"]["evidence_first"]["expected"]

    rank_base = res_base["ranking"]["evidence_first"]
    rank_copies = res_copies["ranking"]["evidence_first"]

    for hid in res_base["items"]:
        id_base = hid["id"]
        if id_base == "H-0001":
            id_copy = "H-0001"
        else:
            idx_base = int(id_base.split("-")[1])
            id_copy = f"H-{idx_base + 2:04d}"

        if hid["outcome"] == "ranked":
            assert rank_base["expected"][id_base] == pytest.approx(rank_copies["expected"][id_copy])
            assert rank_base["p_topk"][id_base] == pytest.approx(rank_copies["p_topk"][id_copy])
            assert rank_base["p_best"][id_base] == pytest.approx(rank_copies["p_best"][id_copy])

    order_base = rank_base["order"]
    order_copies = rank_copies["order"]

    mapped_order_base = []
    for id_base in order_base:
        if id_base == "H-0001":
            mapped_order_base.append("H-0001")
        else:
            idx_base = int(id_base.split("-")[1])
            mapped_order_base.append(f"H-{idx_base + 2:04d}")

    for k in ("expected", "p_topk", "p_best", "order"):
        if k != "order":
            for id_base in rank_base[k]:
                id_copy = "H-0001" if id_base == "H-0001" else f"H-{int(id_base.split('-')[1]) + 2:04d}"
                assert rank_base[k][id_base] == pytest.approx(rank_copies[k][id_copy])

    assert mapped_order_base == order_copies

def test_dominated_hypothesis():
    """
    Adding a dominated hypothesis does not change the expected utility of the others
    within Monte Carlo error, and their p_topk/p_best are unchanged within 4 binomial SEs
    (provided the new hypothesis cannot enter the top). The dominated hypothesis ends up last.

    Why a NON-dominated added hypothesis may legitimately change the others' p_topk:
    Since p_topk is the probability of a hypothesis being among the top k, adding a strong
    contender that takes a place in the top k will necessarily push others out, lowering
    their p_topk. This is why we test with a dominated hypothesis to ensure invariance.

    Conversely, adding a hypothesis that dominates all others DOES lower the p_topk of
    former leaders.
    """
    rng = np.random.default_rng(123)
    specs = [
        IndicatorSpec("x", "ordinal", levels=("lo", "mid", "hi")),
        IndicatorSpec("y", "cardinal", bounds=(0.0, 10.0))
    ]

    # Base pool
    pool = {
        "A": {"x": "hi", "y": 9.0},
        "B": {"x": "mid", "y": 7.0},
        "C": {"x": "lo", "y": 5.0},
        "D": {"x": "hi", "y": 3.0},
        "E": {"x": "mid", "y": 1.0}
    }

    K = 4000
    k_top = 2
    res_base = aggregate(pool, specs, None, K=K, seed=42, k_top=k_top)

    # 1. Add dominated hypothesis
    pool_dom = dict(pool)
    pool_dom["DOM"] = {"x": "lo", "y": 0.0}
    res_dom = aggregate(pool_dom, specs, None, K=K, seed=42, k_top=k_top)

    for h in pool:
        # (a) Expected utility is identical within MC error (in fact exactly the same with same seed)
        # Because we use same seed, cardinal bounds are fixed, and order of submission is same at start.
        # But even if there was MC error, we can check close:
        assert res_base.expected[h] == pytest.approx(res_dom.expected[h], abs=1e-9)

        # (b) p_topk and p_best unchanged within 4 binomial standard errors
        p_topk_base = res_base.p_topk[h]
        p_topk_dom = res_dom.p_topk[h]
        se_topk = math.sqrt(p_topk_base * (1 - p_topk_base) / K)
        assert abs(p_topk_base - p_topk_dom) <= 4 * se_topk + 1e-9

        p_best_base = res_base.p_best[h]
        p_best_dom = res_dom.p_best[h]
        se_best = math.sqrt(p_best_base * (1 - p_best_base) / K)
        assert abs(p_best_base - p_best_dom) <= 4 * se_best + 1e-9

    # (c) The dominated hypothesis is last
    assert res_dom.order[-1] == "DOM"

    # (e) Contrapositive: adding a hypothesis that dominates all others DOES lower p_topk
    pool_god = dict(pool)
    pool_god["GOD"] = {"x": "hi", "y": 10.0}
    res_god = aggregate(pool_god, specs, None, K=K, seed=42, k_top=k_top)

    # Check that at least one of the former leaders has a lower p_topk
    decreased = False
    for h in pool:
        if res_god.p_topk[h] < res_base.p_topk[h] - 1e-9:
            decreased = True
            break
    assert decreased, "Adding a dominating hypothesis should lower p_topk of former leaders."

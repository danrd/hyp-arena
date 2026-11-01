"""Benchmark v2 free part: the formal baseline's logistic regression and the hypothesis texts."""
import json
import random

import numpy as np
import pytest

from scripts import benchmark_run as br


def test_logreg_separates_and_cv_is_out_of_fold():
    rng = np.random.default_rng(0)
    y = np.array([0] * 60 + [1] * 40, float)
    X = np.c_[y * 2 + rng.normal(0, 1, 100), rng.normal(0, 1, 100)]
    s = br.cv_scores(X, y)
    pos, neg = [v for v, l in zip(s, y) if l], [v for v, l in zip(s, y) if not l]
    assert br.auc(pos, neg) > 0.85
    noise = br.cv_scores(rng.normal(0, 1, (100, 3)), y)
    assert abs(br.auc([v for v, l in zip(noise, y) if l], [v for v, l in zip(noise, y) if not l]) - 0.5) < 0.2


def test_design_imputes_missing_fields():
    rows = [{"year": 2015, "enrolment": 100, "phase": 2, "randomized": True, "masked": True, "itype": ["DRUG"], "n_primary": 1, "sponsor": "NIH"},
            {"year": 2019, "enrolment": None, "phase": None, "randomized": None, "masked": None, "itype": [], "n_primary": None, "sponsor": None}]
    X, cols = br.design(rows)
    assert X.shape == (2, len(cols)) and not np.isnan(X).any()
    assert X[1, cols.index("not_ctgov")] == 1 and X[1, cols.index("log_enrolment")] == X[0, cols.index("log_enrolment")]


def test_clip_strips_tags_and_caps_length():
    assert br._clip("<primaryOutcome>Gait  speed</primaryOutcome>") == "Gait speed"
    assert br._clip("word " * 2000).endswith("[...]") and len(br._clip("word " * 2000)) <= br.MAX_FIELD + 6


@pytest.mark.skipif(not br.TEXTS.exists(), reason="private texts not available")
def test_texts_carry_no_registry_id_and_match_units():
    units = {u["id"]: u for u in br._units()}
    texts = [json.loads(l) for l in br.TEXTS.read_text().splitlines()]
    assert sorted(t["id"] for t in texts) == sorted(units)
    for t in texts:
        assert t["id"] not in t["text"] and t["as_of"] == units[t["id"]]["written_on"]
        assert "label" not in t and "outcome" not in t

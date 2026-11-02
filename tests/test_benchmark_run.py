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


def test_served_model_is_recorded():
    from types import SimpleNamespace
    from hyparena.llm.providers import _served_model
    resp = SimpleNamespace(model="gemini-3.6-flash", choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
    comp = SimpleNamespace(create=lambda **kw: resp)
    runner = SimpleNamespace(_client=SimpleNamespace(chat=SimpleNamespace(completions=comp)), last_model=None)
    _served_model(runner)._client.chat.completions.create(model="gemini-3.5-flash", messages=[])
    assert runner.last_model == "gemini-3.6-flash"


def test_gemini_runner_thinking_level_and_cut_reply():
    from types import SimpleNamespace
    from hyparena.llm.gemini_native_runner import GeminiNativeRunner
    def client(payload):
        return SimpleNamespace(post=lambda *a, **kw: SimpleNamespace(status_code=200, json=lambda: payload, text=""))
    cut = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{\"a\":"}]}}],
           "usageMetadata": {"thoughtsTokenCount": 4200, "candidatesTokenCount": 170}}
    r = GeminiNativeRunner(["gemini-3.5-flash"], {"thinking_level": "minimal"}, client=client(cut))
    assert r.config["thinkingConfig"] == {"thinkingLevel": "minimal"}
    with pytest.raises(RuntimeError, match="MAX_TOKENS"):
        r.generate("x")
    ok = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}], "modelVersion": "gemini-3.5-flash"}
    assert GeminiNativeRunner(["gemini-3.5-flash"], {}, client=client(ok)).generate("x") == "{}"


def test_query_fallbacks_for_trial_claims():
    from hyparena.card.verifier import _head, _population_words, _words, queries
    from hyparena.card.models import HypothesisCard
    assert _head("markers of inflammation, immune system markers and other risk factors") == "markers of inflammation"
    assert _words("markers of inflammation", 4) == "markers inflammation"
    card = HypothesisCard.model_validate(json.loads(json.dumps(PILOT_CARD)))
    qs = queries(card.claims[0], card)
    assert qs[-1] == "heat storage older adults" and "simulated heatwave exposure heat storage older adults" in qs
    assert _population_words(card) == "older adults"


PILOT_CARD = json.loads('{"id": "H-0001", "raw_id": "H-0001", "hypothesis_type": "interventional", "claim_plain": "Older adults will store more heat and have higher core body temperatures than younger adults during a prolonged simulated heatwave.", "pico": {"population": {"taxon": "NCBITaxon:9606", "label": "older adults", "strain": "unknown", "sex": "unknown", "age_at_start": "64-80 years"}, "intervention": [{"type": "other", "label": "simulated heatwave exposure", "id": null, "regimen": "9-hour simulated heatwave", "route": "other"}], "comparator": {"type": "chronological_age", "label": "young adults (18-31 years)"}, "outcome": {"endpoint": "biomarker", "metric": "whole-body heat storage"}, "time": "9 hours"}, "claims": [{"id": "c1", "subject": {"label": "simulated heatwave exposure", "id": null, "hallmark": null}, "relation": "changes_biomarker", "object": {"label": "heat storage", "id": null, "hallmark": null}, "qualifiers": {"species": "human", "age_at_start": "64-80 years", "comparator": "younger participants", "direction": "increased"}, "inherited_from_pico": [], "role": "outcome", "source_span": "Older adults will experience greater heat storage throughout the 9-hour simulated heatwave compared to the younger participants.", "note": "", "sex_scope": "unspecified"}, {"id": "c2", "subject": {"label": "heat storage", "id": null, "hallmark": null}, "relation": "promotes", "object": {"label": "body core temperature", "id": null, "hallmark": null}, "qualifiers": {"species": "human", "age_at_start": "64-80 years"}, "inherited_from_pico": [], "role": "mechanism", "source_span": "Consequently, body core temperature will be greater in the older adults and between-group differences will be exacerbated as exposure progresses.", "note": "", "sex_scope": "unspecified"}], "edges": [{"from": "c1", "to": "c2", "type": "supports_if_true"}], "declared_novelty": "information regarding the impact of age on body temperature regulation during prolonged exposure to extreme heat is lacking, as is research on the effectiveness of interventions aimed at reducing heat strain in such situations.", "decisive_experiment": {"system": "human", "endpoint": "body heat storage and rectal temperature", "duration_class": "weeks"}, "declared_alternatives": [], "declared_decision_criteria": "unknown", "risks": ["serious health risk for older adults", "heat strain", "cardiovascular strain", "acute inflammation"]}')  # card of a pilot trial outside the benchmark (public registry text)


def test_or_relation_words_are_bracketed():
    from hyparena.card.verifier import queries
    from hyparena.card.models import HypothesisCard
    card = HypothesisCard.model_validate(json.loads(json.dumps(PILOT_CARD)))
    c = card.claims[0].model_copy(update={"relation": "improves_healthspan_in"})
    assert all("(healthspan OR physical function)" in q for q in queries(c, card) if "healthspan" in q)


def test_graded_admission_counts_adjacent_population_only_when_on():
    from hyparena.card import rules
    from hyparena.card.models import Claim, EvidenceRecord
    claim = Claim.model_validate({"id": "c1", "subject": {"label": "exercise programme"}, "relation": "improves_healthspan_in",
                                  "object": {"label": "human"}, "qualifiers": {"species": "human"}, "role": "outcome", "source_span": "x"})
    rec = EvidenceRecord.model_validate({"source": "PubMed", "record_id": "PMID:1", "epistemic_type": "A_text", "study_type": "rct",
                                         "quote": "q", "quote_role": "finding", "endpoint": "healthspan", "species": "human",
                                         "qualifiers_match": {"population": "no", "intervention_match": "class"}})
    try:
        rules.GRADED_CONTEXT = False
        assert not rules.admissible(rec, claim)
        rules.GRADED_CONTEXT = True
        assert rules.admissible(rec, claim)
        rec.qualifiers_match["species"] = "no"
        assert not rules.admissible(rec, claim)
    finally:
        rules.GRADED_CONTEXT = False

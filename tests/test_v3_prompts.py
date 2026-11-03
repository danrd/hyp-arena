"""Method v3, step 2: templates render, v3 extraction fields are checked against the abstract, alternatives keep only real support."""
import json

from hyparena.card.llm import render
from hyparena.card.models import EvidenceRecord, HypothesisCard
from hyparena.card.verifier import v3_fields
from tests.test_benchmark_run import PILOT_CARD

ABSTRACT = "In this randomized double-blind study, patients were assigned either to treatment (n = 35) or placebo (n = 36). Treatment improved IS (+11.5 ± 17.2; p = 0.041)."


def test_templates_render():
    card = HypothesisCard.model_validate(json.loads(json.dumps(PILOT_CARD)))
    assert "link (method v3)" in render("normalize_card", "v7", text="x", relations="a", hallmarks="b", hint="", history_text="")
    assert "reports_trial" in render("verify_claim", "v6", claim=card.claims[0], claim_plain="x", population="p", intervention="i",
                                     comparator="c", qualifiers="", alternative=False, contrast="", negated=False, endpoint="",
                                     human_healthspan=False, abstracts=[], history_text="")
    out = render("propose_alternatives", "v1", as_of="2018-01-01", claim_plain="x", chain=card.claims, experiment="rct",
                 abstracts=[{"pmid": "1", "year": "2010", "title": "t", "abstract": "a"}], relations="other", history_text="")
    assert "[PMID 1]" in out and "eliminated | weakened | unchanged" in out


def test_v3_fields_keep_only_verbatim_numbers():
    rec = EvidenceRecord(source="PubMed", record_id="PMID:1")
    v3_fields(rec, {"design": "rct", "n_total": 71, "n_quote": "treatment (n = 35) or placebo (n = 36)", "comparison": "between_groups",
                    "effect_reported": "+11.5 ± 17.2", "effect_class": "small", "reports_trial": ""}, ABSTRACT)
    assert rec.design == "rct" and rec.effect_reported == "+11.5 ± 17.2" and rec.comparison == "between_groups"
    assert rec.n_total is None and rec.n_quote                       # 71 is not written in the phrase: the number is dropped
    rec2 = EvidenceRecord(source="PubMed", record_id="PMID:1")
    v3_fields(rec2, {"design": "meta", "n_total": 35, "n_quote": "(n = 35)", "effect_reported": "+99 kg", "effect_class": "huge"}, ABSTRACT)
    assert rec2.n_total == 35 and rec2.design == "unknown" and rec2.effect_reported == "" and rec2.effect_class == "unclear"


def test_proposed_alternatives_keep_only_listed_support():
    from hyparena.card.alternatives_v3 import propose
    from hyparena.llm.fake import FakeLLMClient
    card = HypothesisCard.model_validate(json.loads(json.dumps(PILOT_CARD)))
    alts = propose(FakeLLMClient(0), "deepseek", card, {"123": {"title": "t", "abstract": "a", "year": "2010"}}, "2018-01-01")
    assert len(alts) == 1 and alts[0].support_pmids == ["123"]       # 99999999 was not read; p2 eliminated by both is dropped


def test_v3_pipeline_runs_with_the_fake_llm():
    from hyparena.card.pipeline import run
    text = "Older adults will store more heat than younger adults during a prolonged simulated heatwave, because sweating declines."
    res = run([text], writer="human_registry", config="configs/v3-flash.yaml", fake=True, as_of="2020-01-01", max_calls=60,
              verifiers=["deepseek"])
    assert res["meta"]["method"] == "v3"
    roles = {c.get("role") for c in res["calls"] if c.get("kind") == "llm"}
    assert any(c.get("template") == "normalize_card/v7" for c in res["calls"] if c.get("kind") == "llm")
    assert "propose_alternatives" in roles or res["items"][0]["outcome"] != "ranked"


def test_numbers_written_in_words_are_accepted():
    from hyparena.card.verifier import words_to_numbers
    assert 163 in words_to_numbers("One hundred and sixty-three outpatients with stable chronic heart failure")
    assert 2290 in words_to_numbers("two thousand two hundred ninety residents")
    rec = EvidenceRecord(source="PubMed", record_id="PMID:1")
    v3_fields(rec, {"n_total": 163, "n_quote": "One hundred and sixty-three outpatients"},
              "METHODS: One hundred and sixty-three outpatients with stable chronic heart failure were enrolled.")
    assert rec.n_total == 163

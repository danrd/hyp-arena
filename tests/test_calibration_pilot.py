"""Unit tests for calibration annotation schema, validator, agreement script, and 6-mutation harness.

All fixtures are strictly synthetic (no private hypothesis texts or publisher abstracts).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.calibration import annotation_agreement as agree_mod
from scripts.calibration import pilot10_mutations as mut_mod
from scripts.calibration import validate_annotation as val_mod


def _synthetic_case() -> dict:
    return {
        "case_id": "SYN01",
        "as_of": "2026-11-22",
        "claim": "In aged adults, targeted pathway modulation improves walking speed relative to sham stimulation.",
        "rationale": "Prior observational work links declining pathway tone to slower gait, but direct causal specificity remains untested.",
        "experiment": (
            "Randomize 60 older adults to active directional modulation, reversed control modulation, or sham for 12 weeks. "
            "Verify target engagement via evoked potential shift at week 2 before interpreting walking speed at week 12."
        ),
        "candidate_pmids": ["10000001"],
    }


def _synthetic_annotation_v1() -> dict:
    return {
        "case_id": "SYN01",
        "A": {
            "links": [
                {
                    "id": "L1",
                    "roles": ["mechanism", "novel_claim"],
                    "statement": "Targeted directional pathway modulation specifically restores evoked response compared to reversed control.",
                    "system_or_population": "Older adults",
                    "direction": "Increase in evoked response",
                    "conditions": "Active directional modulation vs reversed control and sham",
                    "status": "explicit",
                    "card_quote": {
                        "text": "direct causal specificity remains untested.",
                        "location": "rationale",
                    },
                    "notes": "Core mechanistic claim.",
                },
                {
                    "id": "L2",
                    "roles": ["outcome"],
                    "statement": "Targeted modulation improves walking speed at week 12.",
                    "system_or_population": "Older adults",
                    "direction": "Increase in walking speed",
                    "conditions": "Relative to sham",
                    "status": "explicit",
                    "card_quote": {
                        "text": "targeted pathway modulation improves walking speed relative to sham stimulation.",
                        "location": "claim",
                    },
                    "notes": "Primary outcome claim.",
                },
            ],
            "measured_outcome": "Walking speed at week 12 and evoked potential shift at week 2.",
            "unresolved_transition": "Long-term fall reduction beyond 12 weeks remains untested.",
        },
        "B": {
            "observations": [
                {
                    "pmid": "10000001",
                    "origin": "fixed_candidates",
                    "link_id": "L1",
                    "contrast": "Young vs older observational cohort",
                    "system_or_population": "Healthy adults",
                    "outcome": "Baseline pathway tone",
                    "direction": "Lower tone in older adults",
                    "relation": "related",
                    "why": "Observational age comparison without active interventional modulation.",
                    "comparison_quote": {
                        "text": "Baseline tone was compared between young and older adults.",
                        "location": "PMID 10000001, Abstract",
                    },
                    "result_quote": {
                        "text": "Older adults exhibited lower baseline tone.",
                        "location": "PMID 10000001, Abstract",
                    },
                    "risk_notes": ["Observational confounding; no intervention."],
                }
            ],
            "additional_search_status": "not_needed",
            "queries": [],
            "already_tested_and_remaining": "Age association was observed; causal interventional specificity remains open.",
            "limits": "Abstract only.",
        },
        "C": {
            "alternative": {
                "explanation": "Nonspecific placebo or general stimulation effect independent of direction.",
                "origin": "stated_by_author",
                "basis": "Sham and reversed arms are included to isolate directional specificity.",
                "basis_quote": {
                    "text": "active directional modulation, reversed control modulation, or sham",
                    "location": "experiment",
                },
                "control_quote": {
                    "text": "Randomize 60 older adults to active directional modulation, reversed control modulation, or sham for 12 weeks.",
                    "location": "experiment",
                },
                "prediction_hypothesis": "Active directional modulation outperforms both reversed control and sham.",
                "prediction_alternative": "Active and reversed modulation yield equivalent changes.",
                "remaining_loophole": None,
                "on_positive": "eliminated",
                "on_null": "unchanged",
                "why": "Reversed control isolates directional effect under matched stimulation exposure.",
            },
            "adequacy": {
                "decisive_contrast": "Active directional modulation vs reversed control and sham.",
                "control_or_outcome_quote": {
                    "text": "Randomize 60 older adults to active directional modulation, reversed control modulation, or sham for 12 weeks.",
                    "location": "experiment",
                },
                "measured_outcome": "Walking speed at week 12.",
                "independent_unit": "Participant",
                "n_units_per_contrast": "20 per arm",
                "precision_basis": "Powered for 0.1 m/s minimal clinically important difference.",
                "engagement_check": "Evoked potential shift at week 2.",
                "engagement_quote": {
                    "text": "Verify target engagement via evoked potential shift at week 2",
                    "location": "experiment",
                },
                "positive_interpretation": "Supports directional mechanism for 12-week walking speed.",
                "null_interpretation": "If engagement is verified, rules out large directional effect.",
                "missing": "Blinding details for outcome assessor.",
            },
            "feasibility": {
                "tool_or_class": "Noninvasive directional stimulator",
                "target_system": "Older adults",
                "evidence_status": "adjacent_only",
                "evidence_quote": {
                    "text": "Baseline tone was compared between young and older adults.",
                    "location": "PMID 10000001, Abstract",
                },
                "key_resource_or_dependency": "Calibrated stimulation hardware and 12-week clinic visits.",
                "tradeoff": "Reversed control arm increases sample size by 50%.",
                "notes": "Adjacent feasibility only.",
            },
        },
    }


def _synthetic_v313_case() -> dict:
    return {
        "id": "SYN_V313",
        "card": {
            "id": "SYN_V313",
            "hypothesis_type": "interventional",
            "claim_plain": "Compound NMD670 improves nerve-evoked muscle force in aged adults with transmission blocking.",
            "pico": {
                "population": {"species": "human", "age_or_stage": "aged", "disease_model": None},
                "intervention": [{"label": "NMD670", "type": "compound"}],
                "comparator": {"label": "placebo"},
                "outcome": {"label": "nerve-evoked quadriceps force", "endpoint": "healthspan"},
            },
            "claims": [
                {
                    "id": "c1",
                    "subject": "NMD670",
                    "relation": "inhibits",
                    "object": "ClC-1 channel",
                    "role": "mechanism",
                    "link": "engagement",
                },
                {
                    "id": "c2",
                    "subject": "NMD670",
                    "relation": "improves_healthspan_in",
                    "object": "aged adults",
                    "role": "outcome",
                    "link": "outcome",
                    "primary": True,
                },
            ],
            "decisive_experiment": {
                "system": "human",
                "endpoint": "function",
                "duration_class": "months",
                "design": "rct",
                "control": "active",
                "n_planned": 64,
                "primary_outcome": "quadriceps torque retention",
                "arms": ["NMD670", "placebo"],
                "span": (
                    "Randomize 64 older adults to NMD670 or placebo in a double-blind crossover. "
                    "Include direct muscle stimulation as an active control to isolate neuromuscular transmission."
                ),
            },
            "proposed_alternatives": [
                {
                    "id": "p1",
                    "subject": "NMD670",
                    "relation": "other",
                    "object": "direct muscle contractility rather than synaptic transmission",
                    "on_positive": "eliminated",
                    "on_negative": "unchanged",
                    "control_span": "Include direct muscle stimulation as an active control to isolate neuromuscular transmission.",
                    "prediction_hypothesis": "Improves nerve-evoked force without changing directly evoked force.",
                    "prediction_alternative": "Improves both nerve-evoked and directly evoked force equally.",
                }
            ],
            "ai_role": "none",
        },
        "verifications": {
            "c1": {
                "id": "c1",
                "evidence": [
                    {
                        "source": "PubMed",
                        "record_id": "PMID:11111111",
                        "epistemic_type": "A_text",
                        "lab_or_cohort": "PMID:11111111",
                        "species": "human",
                        "quote": "Partial ClC-1 inhibition restored excitability in human muscle.",
                        "quote_role": "finding",
                        "endpoint": "mechanism",
                        "effect": "decrease",
                        "qualifiers_match": {"intervention_match": "exact", "species_match": "yes", "population_match": "yes"},
                        "design": "rct",
                        "n_total": 40,
                        "comparison": "between_groups",
                        "effect_class": "medium",
                        "outcome_match": "same",
                        "retrieved_at": "2024",
                    }
                ],
                "counterevidence": [],
            },
            "c2": {
                "id": "c2",
                "evidence": [
                    {
                        "source": "PubMed",
                        "record_id": "PMID:22222222",
                        "epistemic_type": "A_text",
                        "lab_or_cohort": "PMID:22222222",
                        "species": "human",
                        "quote": "Treatment improved muscle force in a randomized trial.",
                        "quote_role": "finding",
                        "endpoint": "healthspan",
                        "effect": "increase",
                        "qualifiers_match": {"intervention_match": "exact", "species_match": "yes", "population_match": "yes"},
                        "design": "rct",
                        "n_total": 80,
                        "comparison": "between_groups",
                        "effect_class": "medium",
                        "outcome_match": "same",
                        "retrieved_at": "2024",
                    }
                ],
                "counterevidence": [],
            },
        },
        "alternatives": {
            "p1": {
                "id": "p1",
                "evidence": [
                    {
                        "source": "PubMed",
                        "record_id": "PMID:33333333",
                        "epistemic_type": "A_text",
                        "lab_or_cohort": "PMID:33333333",
                        "species": "human",
                        "quote": "Chloride conductance shifts can alter direct fiber excitability.",
                        "quote_role": "finding",
                        "endpoint": "mechanism",
                        "effect": "increase",
                        "qualifiers_match": {"intervention_match": "exact", "species_match": "yes", "population_match": "yes"},
                        "design": "observational",
                        "n_total": 50,
                        "comparison": "between_groups",
                        "effect_class": "medium",
                        "outcome_match": "same",
                        "retrieved_at": "2023",
                    }
                ],
                "counterevidence": [],
            }
        },
    }


def test_schema_file_loads_and_defines_core_blocks():
    schema = json.loads(val_mod.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"].startswith("https://json-schema.org/")
    defs = schema["$defs"]
    for key in ("annotation_record", "link_item", "observation_item", "null_outcome_item", "readiness_component"):
        assert key in defs


def test_validator_accepts_valid_v1_and_v11_records():
    cases_by_id = {"SYN01": _synthetic_case()}
    rec_v1 = _synthetic_annotation_v1()
    rep = val_mod.validate_record(rec_v1, cases_by_id=cases_by_id)
    assert rep.errors == []
    assert rep.warnings == []
    assert rep.card_quotes_checked == 6
    assert rep.card_quotes_matched == 6

    rec_v11 = copy.deepcopy(rec_v1)
    rec_v11["schema_version"] = "1.1"
    rec_v11["A"]["links"][0]["human_genetic_anchor"] = {
        "status": "suggestive_human_genetics",
        "pleiotropy_risk": "low",
        "source": "GWAS catalog",
        "notes": "Aligned direction.",
    }
    rec_v11["B"]["observations"][0]["study_mode"] = "exploratory"
    rec_v11["B"]["observations"][0]["worst_domain_risk"] = "high"
    rec_v11["C"]["alternative"]["contrast_id"] = "active_vs_reversed"
    rec_v11["C"]["alternative"]["null_outcomes"] = [
        {
            "contrast_id": "active_vs_reversed",
            "null_definition": "Active equals reversed while both beat sham",
            "on_null": "unchanged",
            "why": "Compatible with nonspecific stimulation.",
        }
    ]
    rec_v11["C"]["adequacy"]["endpoint_best_class"] = "direct_clinical"
    rec_v11["C"]["adequacy"]["tested_scope"] = "direct"
    rec_v11["C"]["adequacy"]["external_validity_flags"] = ["single_sex"]
    rec_v11["C"]["feasibility"]["resource_tier"] = "4_clinical_in_vivo"
    rec_v11["C"]["feasibility"]["safety_flags"] = ["on_target_pleiotropy"]
    rec_v11["C"]["feasibility"]["component_checks"] = [
        {
            "component": "stimulator",
            "target_system": "older adults",
            "evidence_status": "adjacent_only",
        }
    ]
    rep11 = val_mod.validate_record(rec_v11, cases_by_id=cases_by_id)
    assert rep11.errors == []


def test_validator_catches_spliced_ellipsis_and_ungrounded_elimination():
    cases_by_id = {"SYN01": _synthetic_case()}
    bad = _synthetic_annotation_v1()
    bad["A"]["links"][0]["card_quote"]["text"] = "Prior observational work... causal specificity remains untested."
    bad["C"]["alternative"]["control_quote"] = {"text": None, "location": None}
    rep = val_mod.validate_record(bad, cases_by_id=cases_by_id)
    codes = {i.code for i in rep.errors}
    assert "spliced_quote_ellipsis" in codes
    assert "ungrounded_discrimination" in codes


def test_validator_warns_on_eliminated_with_loophole_and_null_without_precision():
    cases_by_id = {"SYN01": _synthetic_case()}
    warn_rec = _synthetic_annotation_v1()
    warn_rec["C"]["alternative"]["remaining_loophole"] = "Electrode polarity may alter local pH."
    warn_rec["C"]["alternative"]["on_null"] = "weakened"
    warn_rec["C"]["adequacy"]["precision_basis"] = None
    rep = val_mod.validate_record(warn_rec, cases_by_id=cases_by_id)
    assert rep.errors == []
    wcodes = {i.code for i in rep.warnings}
    assert "eliminated_with_loophole" in wcodes
    assert "null_credit_without_precision" in wcodes


def test_agreement_metrics_and_kappa():
    assert agree_mod.cohens_kappa([("a", "a"), ("b", "b")]) == 1.0
    assert agree_mod.cohens_kappa([("a", "a"), ("a", "a")]) is None  # zero variance

    r1 = _synthetic_annotation_v1()
    r2 = copy.deepcopy(r1)
    r2["C"]["alternative"]["on_null"] = "weakened"
    r2["B"]["additional_search_status"] = "unavailable"
    r2["B"]["observations"][0]["relation"] = "insufficient"

    res = agree_mod.compute_agreement({"SYN01": r1}, {"SYN01": r2})
    assert res["shared_cases"] == ["SYN01"]
    assert res["lit_access_mismatch_cases"] == ["SYN01"]
    by_field = {m["field"]: m for m in res["metrics"]}
    assert by_field["C.alternative.on_positive"]["agreement_rate"] == 1.0
    assert by_field["C.alternative.on_null"]["agreement_rate"] == 0.0
    md = agree_mod.format_markdown(res)
    assert "Inter-Annotator Agreement Report" in md
    assert "SYN01" in md


def test_pilot_six_mutations_on_synthetic_v313_case():
    suite = mut_mod.run_suite([_synthetic_v313_case()])
    assert suite["n_cases"] == 1
    case_res = suite["cases"][0]
    m = case_res["mutations"]
    assert m["M1_brand_strip"]["passed"] is True
    assert m["M2_background_inflation"]["passed"] is True
    # Confirm M2b catches required-slot inflation sensitivity when background links leak into required slots
    assert m["M2_background_inflation"]["delta_required_leak"] is not None
    assert m["M3_remove_control"]["passed"] is True
    assert m["M3_remove_control"]["delta_I"] < 0
    assert m["M4_downgrade_comparator"]["passed"] is True
    assert m["M5_pilot_vs_confirmatory"]["passed"] is True
    assert m["M6_direct_vs_adjacent_contradiction"]["passed"] is True
    md = mut_mod.format_markdown(suite)
    assert "SYN_V313" in md


def test_diagnostic_search_verifier_alternatives_threats_and_scoring():
    from hyparena.alternatives import alternatives_v3, threats
    from hyparena.card.models import Claim, ClaimVerification, EvidenceRecord, HypothesisCard
    from hyparena.reading import verifier
    from hyparena.scoring import rules_v32, v3_extra
    from hyparena.search import search

    case = _synthetic_v313_case()
    case["card"]["claims"][0]["chain_roles"] = ["mechanism", "novel_contribution"]
    case["card"]["claims"][0]["mechanism_facets"] = {"class": "ClC-1 chloride channel inhibitor", "target": "ClC-1"}
    case["card"]["claims"].append(
        {
            "id": "c_bg",
            "subject": "established background factor",
            "relation": "activates",
            "object": "baseline excitability",
            "role": "premise",
            "link": "step",
            "chain_role": "background",
        }
    )
    case["card"]["claims"].append(
        {
            "id": "c_imp",
            "subject": "acute torque gain",
            "relation": "translates_to",
            "object": "reduced fall risk",
            "role": "translation",
            "link": "step",
            "chain_role": "outcome",
            "is_implicit": True,
        }
    )
    case["card"]["decisive_experiment"]["experimental_unit"] = "participant"
    case["card"]["decisive_experiment"]["n_per_contrast"] = "64 crossover pairs"
    case["card"]["decisive_experiment"]["precision_basis"] = "80% power for 15% torque retention"
    case["card"]["decisive_experiment"]["target_engagement_span"] = "direct muscle stimulation"
    case["card"]["decisive_experiment"]["tested_scope"] = "direct"
    case["card"]["decisive_experiment"]["endpoint_best_class"] = "direct_clinical"
    case["card"]["decisive_experiment"]["safety_flags"] = ["on_target_pleiotropy"]

    card = HypothesisCard.model_validate(case["card"])

    # 1. Two-stage search keeps CAP budget and logs stage provenance
    log: list[dict] = []
    fake_hits = {0: ["101", "102"], 1: ["102", "103"], 2: ["201", "202"], 3: ["203"]}
    call_idx = {"i": 0}

    def _fake_search(q, retmax, as_of):
        idx = call_idx["i"]
        call_idx["i"] += 1
        return fake_hits.get(idx, [])[:retmax]

    pmids, prov = search.retrieve_two_stage(card.claims[0], card, as_of="2026-11-22", retmax=4, log=log, search_fn=_fake_search)
    assert len(pmids) == 4
    assert set(prov.values()) <= {"stage_1_mechanism", "stage_2_contribution"}
    assert log[-1]["kind"] == "search_two_stage"
    assert "ClC-1 chloride channel inhibitor" in " ".join(log[-1]["stage_1_queries"])

    # 2. Verifier guardrail downgrades mismatched direct_contradiction -> related
    mismatch_rec = EvidenceRecord(
        source="PubMed",
        record_id="PMID:55555555",
        species="mouse",
        qualifiers_match={"species_match": "no"},
        actual_contrast="knockout vs wild-type mouse",
        relation_to_claim="direct_contradiction",
    )
    guarded = verifier.enforce_relation_to_claim(mismatch_rec, card.claims[1])
    assert guarded.relation_to_claim == "related"
    assert "species_mismatch" in guarded.notes

    matched_rec = EvidenceRecord(
        source="PubMed",
        record_id="PMID:66666666",
        species="human",
        qualifiers_match={"species_match": "yes", "intervention_match": "exact"},
        outcome_match="same",
        actual_contrast="drug vs placebo in older adults with blocking",
        relation_to_claim="direct_contradiction",
    )
    assert verifier.enforce_relation_to_claim(matched_rec, card.claims[1]).relation_to_claim == "direct_contradiction"

    # 3. Alternatives: screen contradicting PMIDs & require target_engagement_span for on_negative
    ver_c1 = ClaimVerification(id="c1", evidence=[], counterevidence=[matched_rec])
    screen = alternatives_v3.screen_contradicting_pmids({"support_pmids": ["66666666"]}, [ver_c1])
    assert screen["should_route_to_counterevidence"] is True
    assert screen["contradicting_pmids"] == ["66666666"]

    raw_alt = {
        "alt_kind": "negative_barrier",
        "control_span": "Include direct muscle stimulation as an active control to isolate neuromuscular transmission.",
        "loophole": "",
        "on_positive": "unchanged",
        "on_negative": "weakened",
    }
    no_eng = alternatives_v3.ground_discrimination(
        raw_alt, card.decisive_experiment.span, target_engagement_span="", require_engagement_for_negative=True
    )
    assert no_eng["on_negative"] == "unchanged"
    with_eng = alternatives_v3.ground_discrimination(
        raw_alt,
        card.decisive_experiment.span,
        target_engagement_span="direct muscle stimulation",
        require_engagement_for_negative=True,
    )
    assert with_eng["on_negative"] == "weakened"

    # 4. Threats: RoB-2 worst_domain_risk and preclinical diagnostic parser
    assert threats.worst_domain_risk({"a": "eliminated", "b": "eliminated"}) == "low"
    assert threats.worst_domain_risk({"a": "eliminated", "b": "weakened"}) == "some_concerns"
    assert threats.worst_domain_risk({"a": "weakened", "b": "weakened"}) == "high"
    assert threats.worst_domain_risk({"a": "eliminated", "b": "unchanged"}) == "high"

    mouse_card = copy.deepcopy(card)
    mouse_card.decisive_experiment.system = "mouse"
    mouse_card.decisive_experiment.span = "Randomize aged mice balanced by sex to AAV or matched reporter vector; blinded histology."
    base_chk = threats.checklist(mouse_card)
    diag_chk = threats.checklist_diagnostic(mouse_card, parse_preclinical=True)
    assert base_chk["share"] == 0.0  # legacy v3.13 untouched
    assert diag_chk["experimental_preclinical_parser"] is True
    assert diag_chk["share"] > 0.0
    assert diag_chk["worst_domain_risk"] == "high"

    # 5. Scoring diagnostics: background gate, empty novel slot = searched_empty/unchecked, resource_tier split
    ver_empty_novel = ClaimVerification(id="c1", evidence=[], counterevidence=[], search_state="searched_empty")
    ver_out = ClaimVerification.model_validate(case["verifications"]["c2"])
    diag = rules_v32.diagnostic_chain_summary(card, [ver_empty_novel, ver_out])
    assert diag["novel_contribution"]["status"] == "searched_empty"
    assert diag["novel_contribution"]["min_S"] is None
    assert diag["background_gate"]["gate_ok"] is True
    assert "c_imp" in diag["implicit_transitions"]

    fdiag = v3_extra.feasibility_diagnostic(card, offline_readiness=(0.5, "clinical"))
    assert fdiag["resource_tier"] == "4_clinical_in_vivo"
    assert fdiag["execution_readiness"]["readiness_score"] == 0.5
    assert fdiag["execution_readiness"]["precision_basis_present"] is True
    assert fdiag["safety_flags"] == ["on_target_pleiotropy"]

    explant_card = copy.deepcopy(card)
    explant_card.decisive_experiment.span = "Randomize discarded older-donor skin explants ex vivo."
    assert v3_extra.resource_tier(explant_card) == "3_human_ex_vivo_or_pilot"


def test_validator_prefixed_locations_component_quotes_and_precision_prose():
    cases_by_id = {"SYN01": _synthetic_case()}
    rec = _synthetic_annotation_v1()
    rec["A"]["links"][0]["card_quote"]["location"] = "SYN01.rationale"
    rec["C"]["adequacy"]["precision_basis"] = "Не указано (расчёт мощности и минимально значимый эффект отсутствуют)."
    rec["C"]["feasibility"]["component_checks"] = [
        {
            "component": "evoked potential check",
            "target_system": "older adults",
            "evidence_status": "confirmed_in_context",
            "evidence_quote": {
                "text": "Verify target engagement via evoked potential shift at week 2",
                "location": "SYN01.experiment",
            },
        }
    ]
    rep = val_mod.validate_record(rec, cases_by_id=cases_by_id)
    assert rep.errors == []
    assert rep.card_quotes_checked == 7
    assert rep.card_quotes_matched == 7
    wcodes = {i.code for i in rep.warnings}
    assert "negative_text_in_precision_basis" in wcodes


def test_strict_candidate_mutations_and_v19_contrast_extractor():
    from hyparena.card import normalizer

    p19 = REPO_ROOT / "hyparena" / "prompts" / "normalize_card" / "v19.j2"
    assert p19.exists()

    # 1. Strict candidate mode enforces M1 query invariance, M2 guarded background gate, and M4 strict drop
    suite = mut_mod.run_suite([_synthetic_v313_case()], strict_candidate=True)
    m = suite["cases"][0]["mutations"]
    assert m["M1_brand_strip"]["stage1_canonical_query_preserved"] is True
    assert m["M1_brand_strip"]["passed"] is True
    assert m["M2_background_inflation"]["delta_guarded_background"] <= 0.0
    assert m["M2_background_inflation"]["passed"] is True
    assert m["M4_downgrade_comparator"]["had_grounded_discriminating_control"] is True
    assert m["M4_downgrade_comparator"]["passed"] is True

    # 2. Deterministic v19 contrast extractor handles bullet blocks, bare compare expansion, and Prediction: tail stripping
    bullet_text = (
        "Experiment: Apply equal stimulation across tissues:\n"
        "- one contiguous patch;\n"
        "- multiple dispersed patches.\n"
        "Prediction: Only the contiguous patch will sustain hyperpolarization compared to dispersed patches."
    )
    extracted_bullets = normalizer.extract_decisive_contrast_v19(bullet_text)
    assert "- one contiguous patch;" in extracted_bullets
    assert "- multiple dispersed patches." in extracted_bullets
    assert "Prediction:" not in extracted_bullets

    step_text = (
        "4. Wash out initial matrix.\n"
        "5. In one branch suppress endogenous TGFB1 synthesis in intermediate cells. Compare new matrix deposition and viability.\n"
        "Prediction: Suppressing TGFB1 will abolish propagation."
    )
    extracted_step = normalizer.extract_decisive_contrast_v19(step_text)
    assert "In one branch suppress endogenous TGFB1" in extracted_step
    assert "Compare new matrix deposition" in extracted_step

    # 3. derive_chain_roles_v19 prevents background claims from keeping required_for_balance=True
    from hyparena.card.models import HypothesisCard

    card = HypothesisCard.model_validate(_synthetic_v313_case()["card"])
    card.claims[0].part = "premise"
    card.claims[0].stated_as = "known"
    card.claims[0].required_for_balance = True
    normalizer.derive_chain_roles_v19(card)
    assert card.claims[0].chain_roles == ["background"]
    assert card.claims[0].required_for_balance is False
    assert "novel_contribution" in card.claims[1].chain_roles


def test_verify_claim_v23_template_and_ab_packet_scorer():
    import jinja2
    from scripts.calibration import score_ab_packets as sab

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(REPO_ROOT / "hyparena" / "prompts")),
        undefined=jinja2.StrictUndefined,
    )
    tmpl = env.get_template("verify_claim/v23.j2")
    from hyparena.card.models import Claim

    rendered = tmpl.render(
        claim_plain="Test claim.",
        population="older adults",
        intervention="compound X",
        comparator="placebo",
        claim=Claim(id="c1", subject="compound X", relation="improves_healthspan_in", object="human", role="outcome"),
        qualifiers="species: human",
        outcome_label="walking speed",
        alternative=False,
        competitor=False,
        contrast="",
        negated=False,
        endpoint="healthspan",
        human_healthspan=True,
        abstracts=[{"pmid": "10000001", "year": "2024", "review": False, "title": "Trial", "abstract": "Randomized trial."}],
        history_text="",
    )
    assert "relation_to_claim" in rendered
    assert "actual_contrast" in rendered

    # Test normalize scorer on synthetic reply + synthetic dev60 reference
    syn_case = _synthetic_case()
    syn_ref = _synthetic_annotation_v1()
    reply_card = _synthetic_v313_case()["card"]
    reply_card["claims"][0]["source_span"] = "direct causal specificity remains untested."
    reply_card["claims"][0]["chain_roles"] = ["mechanism", "novel_contribution"]
    reply_card["claims"][1]["source_span"] = "targeted pathway modulation improves walking speed relative to sham stimulation."
    reply_card["claims"][1]["chain_roles"] = ["outcome"]
    reply_card["decisive_experiment"]["decisive_contrast_span"] = (
        "Randomize 60 older adults to active directional modulation, reversed control modulation, or sham for 12 weeks."
    )
    norm_score = sab.score_normalize_replies(
        [{"case_id": "SYN01", "card": reply_card}],
        [syn_ref],
        {"SYN01": syn_case},
        {"rows": [{"case_id": "SYN01", "contrast": {"reference_eligible": True, "reference": reply_card["decisive_experiment"]["decisive_contrast_span"]}}]},
    )
    assert norm_score["n_evaluated_cards"] == 1
    assert norm_score["role_overlap"]["novel_claim"]["role_overlap"] == 1
    assert norm_score["decisive_contrast"]["v19_overlap"] == 1

    # Test reader scorer including enforce_relation_to_claim downgrade on mismatched species
    key = {
        "Q01": {"item_id": "Q01", "subset": "anchor_support", "pmid": "111", "expected_relation": "direct_support", "claim_role": "outcome"},
        "Q02": {"item_id": "Q02", "subset": "anchor_trap", "pmid": "222", "expected_relation": "related", "claim_role": "outcome"},
    }
    reader_replies = [
        {
            "item_id": "Q01",
            "actual_contrast": "X vs placebo",
            "actual_system": "older adults",
            "actual_outcome": "walking speed",
            "species": "human",
            "qualifiers_match": {"species_match": "yes", "intervention_match": "exact"},
            "outcome_match": "same",
            "relation_to_claim": "direct_support",
        },
        {
            "item_id": "Q02",
            "actual_contrast": "X vs vehicle in mice",
            "actual_system": "aged mice",
            "actual_outcome": "grip strength",
            "species": "mouse",
            "qualifiers_match": {"species_match": "no", "intervention_match": "exact"},
            "outcome_match": "same",
            "relation_to_claim": "direct_contradiction",  # model mistake caught by enforce_relation_to_claim!
        },
    ]
    r_score = sab.score_reader_replies(reader_replies, key)
    assert r_score["raw_model"]["overall_accuracy"] == 0.5
    assert r_score["post_enforce_guard"]["overall_accuracy"] == 1.0


def test_method_v4_block_c_templates_grounding_and_scorer():
    import jinja2
    from hyparena.alternatives import alternatives_v3
    from hyparena.reading import implementation as impl_mod
    from scripts.calibration import score_ab_packets as sab

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(REPO_ROOT / "hyparena" / "prompts")),
        undefined=jinja2.StrictUndefined,
    )
    alt_t = env.get_template("propose_alternatives/v4.j2")
    impl_t = env.get_template("implementation_readiness/v2.j2")
    assert "conditional_on_negative" in alt_t.render(
        as_of="2026-11-25",
        claim_plain="c",
        chain=[],
        experiment="e",
        registry_text="r",
        abstracts=[],
        relations="other",
        history_text="",
    )
    assert "component_checks" in impl_t.render(
        claim="c", interventions="i", system="human", exp_summary="s", exp_text="t", abstracts_block="a"
    )

    exp_text = (
        "Randomize 60 older adults to active directional modulation, reversed control modulation, or sham for 12 weeks. "
        "Verify target engagement via evoked potential shift at week 2 before interpreting walking speed at week 12."
    )
    # 1. Loophole caps eliminated -> weakened; missing precision caps unconditional on_negative -> unchanged while preserving conditional
    g = alternatives_v3.ground_discrimination_v4(
        {
            "alt_kind": "positive_confounder",
            "control_span": "Randomize 60 older adults to active directional modulation, reversed control modulation, or sham",
            "target_engagement_span": "Verify target engagement via evoked potential shift at week 2",
            "prediction_hypothesis": "Active > reversed",
            "prediction_alternative": "Active == reversed > sham",
            "loophole": "Electrode asymmetry could still differ.",
            "loophole_ruled_out_why": "",
            "on_positive": "eliminated",
            "on_negative": "weakened",
        },
        exp_text,
        precision_status="missing",
    )
    assert g["on_positive"] == "weakened"
    assert g["on_negative"] == "unchanged"
    assert g["conditional_on_negative"] == "weakened"

    # 1b. Unblinded passive-control case (no bias-eliminating control_span, so on_positive='unchanged',
    #     but grounded engagement preserves conditional_on_negative while keeping unconditional on_negative='unchanged')
    g_unblinded = alternatives_v3.ground_discrimination_v4(
        {
            "alt_kind": "positive_confounder",
            "control_span": "",
            "target_engagement_span": "Verify target engagement via evoked potential shift at week 2",
            "prediction_hypothesis": "Active > usual care",
            "prediction_alternative": "Unblinded attention also yields Active > usual care",
            "loophole": "No sham or blinded assessor.",
            "on_positive": "unchanged",
            "on_negative": "unchanged",
            "conditional_on_negative": "weakened",
        },
        exp_text,
        precision_status="missing",
    )
    assert g_unblinded["on_positive"] == "unchanged"
    assert g_unblinded["on_negative"] == "unchanged"
    assert g_unblinded["conditional_on_negative"] == "weakened"

    # 2. Component readiness downgrades unverified quote and computes weak-link min_readiness_score
    abs_map = {"10000001": {"title": "Prior study", "abstract": "Baseline tone was compared between young and older adults."}}
    comp_val = impl_mod.validate_components_v4(
        {
            "resource_tier": "4_clinical_in_vivo",
            "overall_evidence_status": "adjacent_only",
            "evidence_pmid": "10000001",
            "evidence_quote": "Baseline tone was compared between young and older adults.",
            "component_checks": [
                {
                    "component": "intervention_delivery",
                    "target_system": "older adults",
                    "evidence_status": "adjacent_only",
                    "evidence_pmid": "10000001",
                    "evidence_quote": "Baseline tone was compared between young and older adults.",
                },
                {
                    "component": "critical_measurement_or_engagement",
                    "target_system": "older adults",
                    "evidence_status": "confirmed_in_context",
                    "evidence_pmid": "10000001",
                    "evidence_quote": "Fabricated quote absent from abstract.",
                },
            ],
        },
        abs_map,
        experiment_text=exp_text,
    )
    assert comp_val["component_checks"][0]["evidence_status"] == "adjacent_only"
    assert comp_val["component_checks"][1]["evidence_status"] == "insufficient"
    assert comp_val["min_readiness_score"] == 0.0

    # 3. End-to-end Block-C scorer on synthetic case
    syn_case = _synthetic_case()
    syn_ref = _synthetic_annotation_v1()
    syn_ref["C"]["alternative"]["on_positive"] = "weakened"
    syn_ref["C"]["feasibility"]["resource_tier"] = "4_clinical_in_vivo"
    bc_res = sab.score_block_c_replies(
        [
            {
                "case_id": "SYN01",
                "precision_status": "stated_for_contrast",
                "alternatives": [
                    {
                        "alt_kind": "positive_confounder",
                        "control_span": "Randomize 60 older adults to active directional modulation, reversed control modulation, or sham",
                        "target_engagement_span": "Verify target engagement via evoked potential shift at week 2",
                        "prediction_hypothesis": "Active > reversed",
                        "prediction_alternative": "Active == reversed",
                        "loophole": "Minor electrode asymmetry.",
                        "on_positive": "weakened",
                        "on_negative": "unchanged",
                    }
                ],
                "readiness": {
                    "resource_tier": "4_clinical_in_vivo",
                    "overall_evidence_status": "adjacent_only",
                    "evidence_pmid": "10000001",
                    "evidence_quote": "Baseline tone was compared between young and older adults.",
                    "component_checks": [],
                },
            }
        ],
        [syn_ref],
        {"SYN01": syn_case},
        abs_map,
    )
    assert bc_res["n_evaluated"] == 1
    assert bc_res["on_positive_agreement"]["rate"] == 1.0
    assert bc_res["resource_tier_agreement"]["rate"] == 1.0
    assert bc_res["overall_evidence_status_agreement"]["rate"] == 1.0


def test_rules_v4_end_to_end_and_config():
    import yaml
    from hyparena import METHOD_V4_VERSION, METHOD_VERSION
    from hyparena.card.models import ClaimVerification, EvidenceRecord, HypothesisCard
    from hyparena.scoring import rules_v4

    assert METHOD_VERSION == "v3.13"
    assert METHOD_V4_VERSION == "v4.0"
    cfg_v4 = yaml.safe_load((REPO_ROOT / "configs" / "v4-flash.yaml").read_text(encoding="utf-8"))
    assert cfg_v4["method"] == "v4"
    assert cfg_v4["normalize_version"] == "v19"
    assert cfg_v4["verify_version"] == "v23"
    assert cfg_v4["propose_alternatives_version"] == "v4"
    assert cfg_v4["implementation_version"] == "v2"

    case = _synthetic_v313_case()
    case["card"]["claims"][0]["chain_roles"] = ["mechanism", "novel_contribution"]
    case["card"]["claims"][1]["chain_roles"] = ["outcome"]
    case["card"]["decisive_experiment"]["precision_status"] = "missing"
    case["card"]["proposed_alternatives"][0]["discrimination_version"] = "v4"
    case["card"]["proposed_alternatives"][0]["loophole"] = "Residual fiber excitability shift."
    case["card"]["proposed_alternatives"][0]["support_pmids"] = ["33333333"]

    card = HypothesisCard.model_validate(case["card"])
    cvs = [ClaimVerification.model_validate(v) for v in case["verifications"].values()]
    alt_vers = {k: ClaimVerification.model_validate(v) for k, v in case["alternatives"].items()}

    # 1. Baseline v4 evaluation: loophole caps on_positive eliminated -> weakened, missing precision keeps on_negative unchanged
    r_base = rules_v4.evaluate(
        card,
        cvs,
        alt_vers,
        implementation={
            "resource_tier": "4_clinical_in_vivo",
            "overall_evidence_status": "adjacent_only",
            "min_readiness_score": 0.5,
            "component_checks": [{"component": "system_or_population_fit", "evidence_status": "adjacent_only"}],
        },
        experiment_text=card.decisive_experiment.span,
    )
    assert r_base.method_version == "v4.0"
    assert r_base.gate == "pass"
    assert r_base.resource_tier == "4_clinical_in_vivo"
    assert r_base.execution_readiness["readiness_score"] == 0.5

    # 2. M2 invariance: adding supported background claims never raises chain_state
    card_bg = HypothesisCard.model_validate(
        {
            **card.model_dump(),
            "claims": [
                *card.model_dump()["claims"],
                {
                    "id": "c_bg1",
                    "subject": "aging",
                    "relation": "promotes",
                    "object": "transmission blocking",
                    "role": "premise",
                    "link": "pathway",
                    "chain_roles": ["background"],
                },
            ],
        }
    )
    cv_bg = ClaimVerification.model_validate({**case["verifications"]["c1"], "id": "c_bg1"})
    r_bg = rules_v4.evaluate(card_bg, [*cvs, cv_bg], alt_vers, experiment_text=card.decisive_experiment.span)
    assert r_bg.chain_state <= r_base.chain_state

    # 3. Refuted background filters gate ('refuted_background')
    cv_bg_refuted = ClaimVerification(
        id="c_bg1",
        evidence=[],
        counterevidence=[
            EvidenceRecord(
                source="PubMed",
                record_id="PMID:99999999",
                epistemic_type="A_text",
                lab_or_cohort="PMID:99999999",
                species="human",
                quote="Refuted background claim.",
                quote_role="finding",
                endpoint="mechanism",
                effect="no_effect",
                qualifiers_match={"intervention_match": "exact", "species_match": "yes", "population_match": "yes"},
                design="rct",
                n_total=300,
                comparison="between_groups",
                effect_class="none",
                outcome_match="same",
                actual_contrast="active vs placebo",
                relation_to_claim="direct_contradiction",
                retrieved_at="2024",
            )
        ],
    )
    r_refuted = rules_v4.evaluate(card_bg, [*cvs, cv_bg_refuted], alt_vers, experiment_text=card.decisive_experiment.span)
    assert r_refuted.gate == "filtered"
    assert r_refuted.gate_reason == "refuted_background"

    # 4. M6 guard: mismatched species direct_contradiction is downgraded to 'related' and ignored in counterevidence
    cv_mismatched_contra = copy.deepcopy(cvs[1])
    cv_mismatched_contra.counterevidence.append(
        EvidenceRecord(
            source="PubMed",
            record_id="PMID:88888888",
            epistemic_type="A_text",
            lab_or_cohort="PMID:88888888",
            species="mouse",
            quote="Mouse study had no effect.",
            quote_role="finding",
            endpoint="healthspan",
            effect="no_effect",
            qualifiers_match={"intervention_match": "exact", "species_match": "no"},
            design="animal",
            n_total=100,
            comparison="between_groups",
            effect_class="none",
            outcome_match="same",
            actual_contrast="mouse active vs vehicle",
            relation_to_claim="direct_contradiction",
            retrieved_at="2024",
        )
    )
    r_m6 = rules_v4.evaluate(card, [cvs[0], cv_mismatched_contra], alt_vers, experiment_text=card.decisive_experiment.span)
    assert r_m6.chain_state == r_base.chain_state

    # 5. Contradicting alternative PMID is routed out of I when it directly contradicts a required link
    cv_c1_contra = copy.deepcopy(cvs[0])
    cv_c1_contra.counterevidence.append(
        EvidenceRecord(
            source="PubMed",
            record_id="PMID:33333333",
            epistemic_type="A_text",
            lab_or_cohort="PMID:33333333",
            species="human",
            quote="No ClC-1 target engagement.",
            quote_role="finding",
            endpoint="mechanism",
            effect="no_effect",
            qualifiers_match={"intervention_match": "exact", "species_match": "yes"},
            design="rct",
            n_total=80,
            comparison="between_groups",
            effect_class="none",
            outcome_match="same",
            actual_contrast="NMD670 vs placebo",
            relation_to_claim="direct_contradiction",
            retrieved_at="2024",
        )
    )
    r_routed = rules_v4.evaluate(card, [cv_c1_contra, cvs[1]], alt_vers, experiment_text=card.decisive_experiment.span)
    assert r_routed.routed_contradicting_alt_pmids == {"p1": ["33333333"]}
    assert r_routed.I < r_base.I


def test_block_a_v40_fixes():
    from hyparena.card.models import ClaimVerification, HypothesisCard
    from hyparena.card.normalizer import strip_inline_citations
    from hyparena.novelty.novelty_v34 import novelty
    from hyparena.reading.implementation import validate_components_v4
    from hyparena.reports.diversity import pool_clusters
    from hyparena.scoring import rules_v32, rules_v4, v3_extra

    # 1. strip_inline_citations removes PubMed/PMC markdown links, bare URLs, and (PMID: ...) tags cleanly
    dirty = (
        "Restoring field coherence rescues closure. ([pubmed.ncbi.nlm.nih.gov](https://pubmed.ncbi.nlm.nih.gov/22092802/)) "
        "Prior work (PMID: 39641271, PMCID: PMC5299620) and https://europepmc.org/articles/PMC8092380/ concur."
    )
    cleaned = strip_inline_citations(dirty)
    assert "http" not in cleaned and "pubmed" not in cleaned and "PMID" not in cleaned
    assert "Restoring field coherence rescues closure." in cleaned

    # 2. Ex vivo human donor organ is classified as 3_human_ex_vivo_or_pilot even when design=='rct',
    #    and endpoint_for_experiment caps its clinical endpoint at 'biomarker'
    case = _synthetic_v313_case()
    case["card"]["decisive_experiment"]["system"] = "human"
    case["card"]["decisive_experiment"]["design"] = "rct"
    case["card"]["decisive_experiment"]["n_planned"] = 40
    case["card"]["decisive_experiment"]["span"] = "Randomize 40 perfused human atrial preparations with reproducible re-entry."
    ex_card = HypothesisCard.model_validate(case["card"])
    assert v3_extra.is_human_ex_vivo(ex_card) is True
    assert v3_extra.resource_tier(ex_card) == "3_human_ex_vivo_or_pilot"
    assert v3_extra.endpoint_for_experiment("function", "human", card=ex_card) == "biomarker"

    # 3. Scarce human donor organ sample-size check (>3x cited n -> insufficient, min_readiness_score=0.0)
    abs_map = {
        "26059724": {
            "title": "Atrial optical mapping",
            "abstract": "Coronary-perfused human right atria from explanted diseased hearts (n = 8, 43-72 years old) were optically mapped.",
        }
    }
    raw_impl = {
        "resource_tier": "3_human_ex_vivo_or_pilot",
        "overall_evidence_status": "adjacent_only",
        "component_checks": [
            {
                "component": "population_or_model",
                "target_system": "40 perfused human atrial preparations with reproducible re-entry",
                "evidence_status": "adjacent_only",
                "evidence_pmid": "26059724",
                "evidence_quote": "Coronary-perfused human right atria from explanted diseased hearts (n = 8, 43-72 years old) were optically mapped",
            }
        ],
    }
    checked_40 = validate_components_v4(raw_impl, abs_map, n_planned=40)
    assert checked_40["min_readiness_score"] == 0.0
    assert checked_40["overall_evidence_status"] == "insufficient"
    assert checked_40["component_checks"][0]["scale_exceeded"] is True

    checked_16 = validate_components_v4(raw_impl, abs_map, n_planned=16)
    assert checked_16["min_readiness_score"] == 0.5
    assert checked_16["component_checks"][0]["scale_exceeded"] is False

    # 4. Supported background claim prevents false N=None collapse when novel links are searched_empty
    bg_case = _synthetic_v313_case()
    bg_case["card"]["claims"] = [
        {
            "id": "c0",
            "subject": "aging",
            "relation": "decreases_expression",
            "object": "Kir6.2 activity",
            "role": "premise",
            "link": "pathway",
            "chain_roles": ["background"],
        },
        {
            "id": "c1",
            "subject": "pulsatile diazoxide",
            "relation": "activates",
            "object": "granule pool recovery",
            "role": "mechanism",
            "link": "pathway",
            "chain_roles": ["mechanism", "novel_contribution"],
        },
        {
            "id": "c2",
            "subject": "pulsatile diazoxide",
            "relation": "improves_healthspan_in",
            "object": "older diabetic islets",
            "role": "outcome",
            "link": "outcome",
            "chain_roles": ["outcome"],
        },
    ]
    bg_card = HypothesisCard.model_validate(bg_case["card"])
    bg_cvs = [
        ClaimVerification.model_validate({**bg_case["verifications"]["c1"], "id": "c0"}),
        ClaimVerification(id="c1", evidence=[]),
        ClaimVerification(id="c2", evidence=[]),
    ]
    c4, cvs4, alts4, _, _ = rules_v4.prepare_for_v4(bg_card, bg_cvs, {})
    b32 = rules_v32.evaluate(c4, cvs4, alts4, v36=True)
    assert novelty(c4, cvs4, b32) == "new_link"

    # 5. Offline pool_clusters groups mechanistic siblings and produces top_distinct
    c_skin1 = HypothesisCard.model_validate({**bg_case["card"], "id": "W1", "claim_plain": "Restoring wound electric field rescues keratinocyte closure in older skin."})
    c_skin2 = HypothesisCard.model_validate({**bg_case["card"], "id": "W2", "claim_plain": "Reversing epidermal wound electric field tests keratinocyte direction in aged skin."})
    cl_res = pool_clusters({"W1": c_skin1, "W2": c_skin2, "A1": ex_card}, {"evidence": ["W1", "W2", "A1"]})
    assert len(cl_res["clusters"]) == 1 and set(cl_res["clusters"][0]["members"]) == {"W1", "W2"}
    assert [r["id"] for r in cl_res["top_distinct"]["evidence"]] == ["W1", "A1"]







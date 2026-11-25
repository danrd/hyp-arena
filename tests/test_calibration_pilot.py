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

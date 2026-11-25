"""Offline baseline & 6-mutation diagnostic harness for Hyp-Arena v3.13.

Implements Section 4 of docs/plans/evaluation-calibration-2026-11-25.md without making any
LLM or network calls. Reuses saved v3.13 cards, verifications, and alternatives to measure
exact baseline behavior and test six controlled input mutations:

  M1. Strip proprietary/brand name in intervention label while keeping mechanism/class.
  M2. Add two well-supported background links (chain inflation / dilution test).
  M3. Remove decisive control sentence from decisive_experiment.span and re-ground alternatives.
  M4. Downgrade decisive control/arms to generic "usual care / standard care".
  M5. Compare short pilot (weeks, n=30) vs confirmatory trial (years, n=400).
  M6. Inject direct contradiction on mandatory outcome link vs on an adjacent background link.

Usage:
    python scripts/calibration/pilot10_mutations.py path/to/cases.json --ids H13 H06 H02 H07 H04 H14 H16 H17
    python scripts/calibration/pilot10_mutations.py path/to/cases.json --json
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hyparena.alternatives import alternatives_v3, threats
from hyparena.card.models import (
    Claim,
    ClaimVerification,
    EvidenceRecord,
    HypothesisCard,
    ProposedAlternative,
)
from hyparena.scoring import rules_v32, v3_extra


# Production v3.13 evaluation flags.
V313_EVAL_KWARGS = dict(
    fold=False,
    neutral_unverified=True,
    v34=True,
    null_power=True,
    v35=True,
    v36=True,
)

BRAND_PATTERNS = [
    (re.compile(r"\bNMD670\b", re.IGNORECASE), "partial ClC-1 chloride channel inhibitor"),
    (re.compile(r"\bURO-902\b", re.IGNORECASE), "hMaxi-K (BK channel) plasmid gene transfer"),
    (re.compile(r"\bTAT-Gap19\b", re.IGNORECASE), "selective Cx43 hemichannel blocking peptide"),
    (re.compile(r"\bCx43-M2\b", re.IGNORECASE), "connexin-43 hemichannel activating antibody"),
    (re.compile(r"\bDermacorder®?\b", re.IGNORECASE), "noninvasive surface electric field sensor"),
]


def _load_card_and_verifications(
    case_dict: dict[str, Any],
) -> tuple[HypothesisCard, list[ClaimVerification], dict[str, ClaimVerification]]:
    card = HypothesisCard.model_validate(case_dict["card"])
    ver_list: list[ClaimVerification] = []
    raw_vers = case_dict.get("verifications") or []
    if isinstance(raw_vers, dict):
        raw_vers = list(raw_vers.values())
    for item in raw_vers:
        ver_list.append(ClaimVerification.model_validate(item))

    alt_vers: dict[str, ClaimVerification] = {}
    raw_alts = case_dict.get("alternatives") or case_dict.get("alt_verifications") or {}
    if isinstance(raw_alts, dict):
        for k, v in raw_alts.items():
            if isinstance(v, dict) and ("evidence" in v or "counterevidence" in v):
                alt_vers[str(k)] = ClaimVerification.model_validate(v)
    return card, ver_list, alt_vers


def _offline_feasibility(card: HypothesisCard, readiness_score: float = 0.0) -> dict[str, Any]:
    """Compute v3_extra operational feasibility strictly offline (no ChEMBL/CT.gov network calls)."""
    e = card.decisive_experiment
    sys_score = v3_extra.SYSTEM_COST.get(e.system)
    dur_score = v3_extra.DURATION_COST.get(e.duration_class)
    n_score = v3_extra.sample_size_score(e) if hasattr(v3_extra, "sample_size_score") else v3_extra._n_score(e.n_planned)
    parts = [s for s in (sys_score, dur_score, n_score) if s is not None]
    denom = len(parts) + 1  # matches v3_extra reserved readiness slot
    total = round((sum(parts) + readiness_score) / denom, 4)
    return {
        "feasibility": total,
        "system": sys_score,
        "duration": dur_score,
        "n_planned": e.n_planned,
        "n_score": n_score,
        "readiness_slot": readiness_score,
    }


def _evaluate_snapshot(
    card: HypothesisCard,
    ver_list: list[ClaimVerification],
    alt_vers: Optional[dict[str, ClaimVerification]] = None,
) -> dict[str, Any]:
    res = rules_v32.evaluate(card, ver_list, alt_verifications=alt_vers or None, **V313_EVAL_KWARGS)
    rd = res.as_dict()
    fb = _offline_feasibility(card)
    chk = threats.checklist(card)
    alt_fates = [
        {
            "id": a.id,
            "on_positive": a.on_positive,
            "on_negative": a.on_negative,
            "has_control_span": bool((a.control_span or "").strip()),
        }
        for a in (card.proposed_alternatives or [])
    ]
    return {
        "P": round(float(rd["P"]), 4),
        "I": round(float(rd["I"]), 4),
        "headroom_I": round(float(rd["headroom_I"]), 4),
        "scope": rd.get("scope"),
        "gate": rd.get("gate"),
        "chain_state": None if rd.get("chain_state") is None else round(float(rd["chain_state"]), 4),
        "support_share": None if rd.get("support_share") is None else round(float(rd["support_share"]), 4),
        "silent_share": None if rd.get("silent_share") is None else round(float(rd["silent_share"]), 4),
        "feasibility": fb["feasibility"],
        "feasibility_parts": fb,
        "threat_checklist_applied": bool(chk),
        "threat_checklist_count": len(chk) if isinstance(chk, dict) else 0,
        "alternatives": alt_fates,
    }


def _strip_brands(text: str) -> tuple[str, bool]:
    changed = False
    out = text
    for pat, repl in BRAND_PATTERNS:
        new_out, n = pat.subn(repl, out)
        if n:
            changed = True
            out = new_out
    if not changed and out.strip():
        out = f"{out.strip()} (class-level description)"
        changed = True
    return out, changed


def _reground_alternatives(card: HypothesisCard) -> list[dict[str, Any]]:
    """Re-apply alternatives_v3.ground_discrimination on all proposed alternatives."""
    exp_text = card.decisive_experiment.span or ""
    changes: list[dict[str, Any]] = []
    updated: list[ProposedAlternative] = []
    for alt in card.proposed_alternatives or []:
        raw = alt.model_dump()
        before = (raw.get("on_positive"), raw.get("on_negative"))
        grounded = alternatives_v3.ground_discrimination(dict(raw), exp_text)
        after = (grounded.get("on_positive"), grounded.get("on_negative"))
        if before != after:
            changes.append({"id": alt.id, "before": before, "after": after})
        updated.append(ProposedAlternative.model_validate(grounded))
    card.proposed_alternatives = updated
    return changes


def _make_synthetic_record(
    pmid: str,
    effect: str = "increase",
    design: str = "rct",
    species: str = "human",
    n_total: int = 200,
    endpoint: str = "healthspan",
    population_match: str = "yes",
) -> EvidenceRecord:
    return EvidenceRecord(
        source="PubMed",
        record_id=f"PMID:{pmid}",
        epistemic_type="A_text",
        lab_or_cohort=f"PMID:{pmid}",
        species=species,
        strain="unknown",
        sex="unknown",
        dose="unknown",
        age_at_start="unknown",
        quote="Synthetic controlled calibration mutation record.",
        quote_role="finding",
        endpoint=endpoint,
        effect=effect,
        qualifiers_match={
            "intervention_match": "exact",
            "species_match": "yes",
            "population_match": population_match,
        },
        design=design,
        n_total=n_total,
        comparison="between_groups",
        effect_reported="synthetic calibration mutation effect",
        effect_class="medium",
        outcome_match="same",
        outcome_measure="primary outcome",
        retrieved_at="2024",
    )


def run_mutations_on_case(case_dict: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case_dict.get("id") or case_dict.get("card", {}).get("id") or "unknown")
    base_card, base_vers, base_alt_vers = _load_card_and_verifications(case_dict)
    baseline = _evaluate_snapshot(base_card, base_vers, base_alt_vers)

    mutations: dict[str, Any] = {}

    # --- M1: Brand stripping / class-level paraphrase ---
    m1_card = copy.deepcopy(base_card)
    m1_changed_labels: list[tuple[str, str]] = []
    for iv in m1_card.pico.intervention:
        new_lbl, changed = _strip_brands(iv.label)
        if changed:
            m1_changed_labels.append((iv.label, new_lbl))
            iv.label = new_lbl
    m1_snap = _evaluate_snapshot(m1_card, base_vers, base_alt_vers)
    mutations["M1_brand_strip"] = {
        "description": "Replace proprietary/brand intervention name with class-level description.",
        "changed_labels": m1_changed_labels,
        "baseline_P": baseline["P"],
        "mutated_P": m1_snap["P"],
        "baseline_feasibility": baseline["feasibility"],
        "mutated_feasibility": m1_snap["feasibility"],
        "invariant": "Class-level paraphrase must preserve offline score on fixed verifications (search-layer recall checked separately).",
        "passed": m1_snap["P"] == baseline["P"],
    }

    # --- M2: Background chain inflation (+2 strongly supported background links) ---
    m2_card = copy.deepcopy(base_card)
    m2_vers = copy.deepcopy(base_vers)
    for k in (1, 2):
        cid = f"bg_pad_{k}"
        m2_card.claims.append(
            Claim(
                id=cid,
                subject=f"established upstream pathway {k}",
                relation="activates",
                object=f"known physiological intermediate {k}",
                role="premise",
                link="step",
            )
        )
        m2_vers.append(
            ClaimVerification(
                id=cid,
                evidence=[
                    _make_synthetic_record(f"990000{k}{j}", design="rct", species="human", n_total=300)
                    for j in range(1, 5)
                ],
                counterevidence=[],
            )
        )
    m2_snap = _evaluate_snapshot(m2_card, m2_vers, base_alt_vers)

    # Also test sensitivity if a background link is erroneously promoted to required_for_balance=True.
    m2_req_card = copy.deepcopy(m2_card)
    for cl in m2_req_card.claims:
        if cl.id.startswith("bg_pad_"):
            cl.required_for_balance = True
    m2_req_snap = _evaluate_snapshot(m2_req_card, m2_vers, base_alt_vers)

    cs_base = baseline["chain_state"]
    cs_m2 = m2_snap["chain_state"]
    cs_m2_req = m2_req_snap["chain_state"]
    cs_delta = None if (cs_base is None or cs_m2 is None) else round(cs_m2 - cs_base, 4)
    cs_req_delta = None if (cs_base is None or cs_m2_req is None) else round(cs_m2_req - cs_base, 4)
    mutations["M2_background_inflation"] = {
        "description": "Append 2 strongly supported background premise links to the chain (unmarked and marked required).",
        "baseline_chain_state": cs_base,
        "mutated_chain_state": cs_m2,
        "delta_chain_state": cs_delta,
        "required_leak_chain_state": cs_m2_req,
        "delta_required_leak": cs_req_delta,
        "baseline_support_share": baseline["support_share"],
        "mutated_support_share": m2_snap["support_share"],
        "invariant": "Adding known background links must NOT inflate chain_state (delta <= 0); required_leak tracks sensitivity if normalizer over-marks background links.",
        "passed": (cs_delta is not None and cs_delta <= 1e-6),
    }

    # --- M3: Remove decisive control span and re-ground alternatives ---
    m3_card = copy.deepcopy(base_card)
    span = m3_card.decisive_experiment.span or ""
    removed_any = False
    for alt in m3_card.proposed_alternatives or []:
        cspan = (alt.control_span or "").strip()
        if cspan and cspan in span:
            span = span.replace(cspan, "[CONTROL REMOVED]")
            removed_any = True
    if not removed_any:
        span = "Open-label single-arm observation without active control."
    m3_card.decisive_experiment.span = span
    m3_changes = _reground_alternatives(m3_card)
    m3_snap = _evaluate_snapshot(m3_card, base_vers, base_alt_vers)
    still_claims_elim = any(
        a["on_positive"] == "eliminated" or a["on_negative"] == "eliminated"
        for a in m3_snap["alternatives"]
    )
    mutations["M3_remove_control"] = {
        "description": "Remove quoted control from decisive_experiment.span and re-run ground_discrimination.",
        "reground_changes": m3_changes,
        "baseline_I": baseline["I"],
        "mutated_I": m3_snap["I"],
        "delta_I": round(m3_snap["I"] - baseline["I"], 4),
        "still_claims_eliminated": still_claims_elim,
        "invariant": "Removing verbatim control must drop 'eliminated' credit and not increase I.",
        "passed": (not still_claims_elim) and (m3_snap["I"] <= baseline["I"] + 1e-6),
    }

    # --- M4: Downgrade decisive comparator to generic usual care ---
    m4_card = copy.deepcopy(base_card)
    m4_card.decisive_experiment.control = "usual_care"
    m4_card.decisive_experiment.arms = ["intervention", "usual care"]
    m4_card.decisive_experiment.span = (
        f"Compare intervention against usual care alone measuring "
        f"{m4_card.decisive_experiment.primary_outcome or 'outcome'}."
    )
    m4_changes = _reground_alternatives(m4_card)
    m4_snap = _evaluate_snapshot(m4_card, base_vers, base_alt_vers)
    mutations["M4_downgrade_comparator"] = {
        "description": "Replace active/factorial comparator with generic 'usual care'.",
        "reground_changes": m4_changes,
        "baseline_I": baseline["I"],
        "mutated_I": m4_snap["I"],
        "delta_I": round(m4_snap["I"] - baseline["I"], 4),
        "invariant": "Downgrading active/factorial contrast to usual care must not increase I.",
        "passed": m4_snap["I"] <= baseline["I"] + 1e-6,
    }

    # --- M5: Short pilot vs confirmatory trial ---
    m5_pilot = copy.deepcopy(base_card)
    m5_pilot.decisive_experiment.duration_class = "weeks"
    m5_pilot.decisive_experiment.n_planned = 30
    m5_conf = copy.deepcopy(base_card)
    m5_conf.decisive_experiment.duration_class = "years"
    m5_conf.decisive_experiment.n_planned = 400
    snap_pilot = _evaluate_snapshot(m5_pilot, base_vers, base_alt_vers)
    snap_conf = _evaluate_snapshot(m5_conf, base_vers, base_alt_vers)
    mutations["M5_pilot_vs_confirmatory"] = {
        "description": "Compare short pilot (weeks, n=30) vs confirmatory study (years, n=400) on identical claims.",
        "pilot_feasibility": snap_pilot["feasibility"],
        "confirmatory_feasibility": snap_conf["feasibility"],
        "pilot_I": snap_pilot["I"],
        "confirmatory_I": snap_conf["I"],
        "invariant": "Pilot scores higher on operational feasibility while confirmatory study does not score lower on I.",
        "passed": (
            snap_pilot["feasibility"] > snap_conf["feasibility"]
            and snap_conf["I"] >= snap_pilot["I"] - 1e-6
        ),
    }

    # --- M6: Direct contradiction on mandatory outcome link vs adjacent non-mandatory link ---
    outcome_claims = [c for c in base_card.claims if c.role == "outcome"]
    target_cid = outcome_claims[0].id if outcome_claims else (base_card.claims[-1].id if base_card.claims else None)

    m6_direct_vers = copy.deepcopy(base_vers)
    if target_cid is not None:
        contra_rec = _make_synthetic_record(
            "990000991", effect="no_effect", design="rct", species="human", n_total=300, endpoint="healthspan"
        )
        matched = [v for v in m6_direct_vers if v.id == target_cid]
        if matched:
            matched[0].counterevidence.append(contra_rec)
        else:
            m6_direct_vers.append(ClaimVerification(id=target_cid, evidence=[], counterevidence=[contra_rec]))
    snap_direct = _evaluate_snapshot(base_card, m6_direct_vers, base_alt_vers)

    m6_adj_card = copy.deepcopy(base_card)
    m6_adj_vers = copy.deepcopy(base_vers)
    adj_cid = "adjacent_nonmandatory_1"
    m6_adj_card.claims.append(
        Claim(
            id=adj_cid,
            subject="adjacent marker",
            relation="associated_with",
            object="unrelated secondary trait",
            role="analog",
            link=None,
            required_for_balance=False,
        )
    )
    m6_adj_vers.append(
        ClaimVerification(
            id=adj_cid,
            evidence=[],
            counterevidence=[
                _make_synthetic_record(
                    "990000992",
                    effect="no_effect",
                    design="observational",
                    species="mouse",
                    n_total=40,
                    endpoint="mechanism",
                    population_match="no",
                )
            ],
        )
    )
    snap_adj = _evaluate_snapshot(m6_adj_card, m6_adj_vers, base_alt_vers)
    mutations["M6_direct_vs_adjacent_contradiction"] = {
        "description": "Inject strong human RCT counterevidence on mandatory outcome link vs mouse observational counterevidence on non-mandatory background link.",
        "target_outcome_claim_id": target_cid,
        "baseline_P": baseline["P"],
        "direct_contradiction_P": snap_direct["P"],
        "adjacent_contradiction_P": snap_adj["P"],
        "baseline_chain_state": baseline["chain_state"],
        "direct_contradiction_chain_state": snap_direct["chain_state"],
        "adjacent_contradiction_chain_state": snap_adj["chain_state"],
        "invariant": "Direct contradiction on mandatory outcome link must reduce P and chain_state strictly below baseline and below adjacent-only contradiction.",
        "passed": (
            snap_direct["P"] < baseline["P"]
            and (
                snap_direct["chain_state"] is not None
                and baseline["chain_state"] is not None
                and snap_direct["chain_state"] < baseline["chain_state"]
            )
            and snap_direct["P"] < snap_adj["P"]
        ),
    }

    return {
        "case_id": case_id,
        "baseline": baseline,
        "mutations": mutations,
    }


def run_suite(cases: list[dict[str, Any]], ids: Optional[list[str]] = None) -> dict[str, Any]:
    if ids:
        wanted = set(ids)
        cases = [c for c in cases if str(c.get("id") or c.get("card", {}).get("id")) in wanted]
    results = [run_mutations_on_case(c) for c in cases]

    mutation_names = [
        "M1_brand_strip",
        "M2_background_inflation",
        "M3_remove_control",
        "M4_downgrade_comparator",
        "M5_pilot_vs_confirmatory",
        "M6_direct_vs_adjacent_contradiction",
    ]
    summary = {}
    for m in mutation_names:
        passed = sum(1 for r in results if r["mutations"][m]["passed"])
        summary[m] = {"passed": passed, "total": len(results)}
    return {
        "n_cases": len(results),
        "summary": summary,
        "cases": results,
    }


def format_markdown(suite: dict[str, Any]) -> str:
    lines = [
        "# Hyp-Arena v3.13 Offline 6-Mutation Diagnostic Report",
        "",
        f"Cases evaluated: {suite['n_cases']}",
        "",
        "## Invariant Pass Summary",
        "",
        "| Mutation | Passed / Total |",
        "| --- | ---: |",
    ]
    for m, stats in suite["summary"].items():
        lines.append(f"| `{m}` | {stats['passed']} / {stats['total']} |")

    lines.extend(
        [
            "",
            "## Per-Case Baseline & Key Deltas",
            "",
            "| Case | Base P | Base I | Base CS | Base Feas | M2 ΔCS (step / req-leak) | M3 ΔI (no ctrl) | M5 Feas (pilot→conf) | M6 P (direct vs adj) |",
            "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |",
        ]
    )
    for r in suite["cases"]:
        b = r["baseline"]
        m2 = r["mutations"]["M2_background_inflation"]
        m3 = r["mutations"]["M3_remove_control"]
        m5 = r["mutations"]["M5_pilot_vs_confirmatory"]
        m6 = r["mutations"]["M6_direct_vs_adjacent_contradiction"]
        cs_str = "n/a" if m2["delta_chain_state"] is None else f"{m2['delta_chain_state']:+.4f}"
        req_str = "n/a" if m2["delta_required_leak"] is None else f"{m2['delta_required_leak']:+.4f}"
        lines.append(
            f"| `{r['case_id']}` | {b['P']:.3f} | {b['I']:.3f} | {b['chain_state']} | {b['feasibility']} "
            f"| {cs_str} / {req_str} ({'PASS' if m2['passed'] else 'FAIL'}) "
            f"| {m3['delta_I']:+.4f} ({'PASS' if m3['passed'] else 'FAIL'}) "
            f"| {m5['pilot_feasibility']}→{m5['confirmatory_feasibility']} ({'PASS' if m5['passed'] else 'FAIL'}) "
            f"| {m6['direct_contradiction_P']:.3f} vs {m6['adjacent_contradiction_P']:.3f} ({'PASS' if m6['passed'] else 'FAIL'}) |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline v3.13 baseline and 6 controlled mutations on saved cases.json.")
    parser.add_argument("cases_json", type=Path, help="Path to saved v3.13 cases.json (list of case dicts).")
    parser.add_argument("--ids", nargs="*", default=None, help="Optional subset of case IDs (e.g. H13 H06 H02).")
    parser.add_argument("--json", action="store_true", help="Output full JSON report.")
    args = parser.parse_args(argv)

    cases = json.loads(args.cases_json.read_text(encoding="utf-8"))
    if isinstance(cases, dict) and "cases" in cases:
        cases = cases["cases"]
    suite = run_suite(cases, ids=args.ids)
    if args.json:
        print(json.dumps(suite, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(suite))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Method v4.0 scorer and evaluator (`v4.0`, adopted 2026-11-27).

Consolidates the three empirically validated architectural upgrades over v3.13 (`rules_v32` + `v3_extra`):
  1. Explicit chain roles & guarded background gate (`normalize_card/v19`):
     - Background claims (`chain_roles == ['background']` or `chain_role == 'background'` alone) are folded
       into a single gate block: refuted background filters the hypothesis (`gate = 'filtered'`,
       `gate_reason = 'refuted_background'`), while adding or splitting background claims never increases
       `chain_state` or adds required balance slots (`M2` invariance).
     - `novel_contribution` claims (non-background) occupy required slots, and empty slots record explicit
       `searched_empty` vs `unchecked` status (never receiving a free +1.0 positive credit).
  2. Two-step factual comparison & relation-to-claim enforcement (`verify_claim/v23`):
     - Applies `verifier.enforce_relation_to_claim(rec, claim)` before weighing any record.
     - When `relation_to_claim` is present, only `direct_support` counts on `evidence` and only guarded
       `direct_contradiction` counts on `counterevidence` (`related`/`irrelevant`/`insufficient` count 0.0),
       preventing adjacent findings from causing false refutations or false direct support (`M6`).
     - Legacy saved records (`relation_to_claim is None`) remain 100% backward-compatible with `rules_v32`.
  3. Contrast-bound alternatives, conditional vs unconditional nulls, and 3-component weak-link readiness
     (`propose_alternatives/v4` + `implementation_readiness/v2`):
     - Screens `alt.support_pmids` via `screen_contradicting_pmids()` so direct refutations of a required
       chain link are routed out of `I` rather than boosting informativeness.
     - Grounds each alternative via `ground_discrimination_v4()` against `experiment_text` (`control_span`
       verbatim check, loophole cap `eliminated -> weakened`, and `target_engagement_span` +
       `precision_status == 'stated_for_contrast'` required for unconditional `on_negative` credit).
     - Computes preclinical/clinical `worst_domain_risk` via `threats.checklist_diagnostic()`.
     - Splits `resource_tier` (`1_in_vitro .. 4_clinical_in_vivo`) from within-tier `execution_readiness`
       using weak-link `min_readiness_score` across verified components (`implementation_readiness/v2`).
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Optional

from hyparena.alternatives import alternatives_v3, threats
from hyparena.card.models import Claim, ClaimVerification, EvidenceRecord, HypothesisCard, ProposedAlternative
from hyparena.reading import verifier
from hyparena.scoring import rules_v32 as r32, v3_extra


@dataclass
class V4Result:
    method_version: str = "v4.0"
    gate: str = "pass"
    gate_reason: str = ""
    P: float = 0.0
    P_lo: float = 0.0
    P_hi: float = 0.0
    I: float = 0.0
    headroom_I: Optional[float] = None
    V: float = 0.0
    scope: str = "local"
    chain_state: float = 0.0
    support_share: float = 0.0
    coverage: float = 0.0
    coverage_counts: Optional[tuple[int, int]] = None
    weakest: str = ""
    links: dict[str, list[float]] = field(default_factory=dict)
    chain_summary: dict = field(default_factory=dict)
    checklist: Optional[dict] = None
    worst_domain_risk: str = "unknown"
    resource_tier: Optional[str] = None
    feasibility: float = 0.0
    execution_readiness: dict = field(default_factory=dict)
    routed_contradicting_alt_pmids: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _is_pure_background(cl: Claim) -> bool:
    roles = set(getattr(cl, "chain_roles", None) or [])
    if getattr(cl, "chain_role", None):
        roles.add(cl.chain_role)
    if roles:
        return roles == {"background"}
    return cl.part == "premise"


def _filter_records_v4(
    recs: list[EvidenceRecord],
    claim: Claim,
    *,
    against: bool,
) -> list[EvidenceRecord]:
    out: list[EvidenceRecord] = []
    for rec in recs:
        guarded = verifier.enforce_relation_to_claim(rec, claim)
        rel = guarded.relation_to_claim
        if rel is None:
            out.append(guarded)
        elif not against and rel == "direct_support":
            out.append(guarded)
        elif against and rel == "direct_contradiction":
            out.append(guarded)
    return out


def prepare_for_v4(
    card: HypothesisCard,
    ver_claims: list[ClaimVerification],
    alt_verifications: Optional[dict[str, ClaimVerification]] = None,
    *,
    experiment_text: str = "",
) -> tuple[HypothesisCard, list[ClaimVerification], dict[str, ClaimVerification], dict[str, list[str]], bool]:
    """Return deep-copied `(card_v4, ver_claims_v4, alt_ver_v4, routed_alt_pmids, bg_refuted)` with all v4
    deterministic guards applied, without mutating caller inputs.
    """
    c4 = copy.deepcopy(card)
    by_claim_id = {c.id: c for c in c4.claims}

    # 1. Enforce v23 relation_to_claim guard on every claim verification
    cvs4: list[ClaimVerification] = []
    for cv in ver_claims:
        cv_copy = copy.deepcopy(cv)
        cl = by_claim_id.get(cv_copy.id) or cv_copy.claim or Claim(
            id=cv_copy.id, subject="intervention", relation="other", object="outcome"
        )
        cv_copy.evidence = _filter_records_v4(cv_copy.evidence, cl, against=False)
        cv_copy.counterevidence = _filter_records_v4(cv_copy.counterevidence, cl, against=True)
        cvs4.append(cv_copy)

    # 2. Fold pure background claims into a single gate check & ensure novel_contribution claims are required
    bg_refuted = False
    cv_map = {cv.id: cv for cv in cvs4}
    with r32.method(v36=True):
        for cl in c4.claims:
            roles = r32._claim_roles(cl)
            if _is_pure_background(cl):
                cl.required_for_balance = False
                cv = cv_map.get(cl.id)
                if cv is not None:
                    f_w = r32.side_weight(cv.evidence, cl, False, True, True)
                    a_w = r32.side_weight(cv.counterevidence, cl, True, True, True)
                    s_pt = r32.link_point(f_w, a_w)
                    if a_w > f_w and s_pt <= 0.25:
                        bg_refuted = True
                # Keep pure background off the scored positive chain so M2 background inflation is strictly <= 0
                cl.part = "premise"
                cl.link = None
            elif "novel_contribution" in roles:
                cl.required_for_balance = True

    # 3. Ground competing alternatives against experiment_text & screen contradicting support_pmids
    exp_txt = experiment_text or c4.decisive_experiment.span or ""
    prec_status = getattr(c4.decisive_experiment, "precision_status", None) or (
        "stated_for_contrast" if (c4.decisive_experiment.precision_basis or "").strip() else "missing"
    )
    alt_ver4 = copy.deepcopy(alt_verifications or {})
    routed_pmids: dict[str, list[str]] = {}
    grounded_alts: list[ProposedAlternative] = []
    for alt in c4.proposed_alternatives:
        scr = alternatives_v3.screen_contradicting_pmids(alt.model_dump(), cvs4)
        if scr["should_route_to_counterevidence"]:
            bad_set = {f"PMID:{p}" for p in scr["contradicting_pmids"]}
            routed_pmids[alt.id] = scr["contradicting_pmids"]
            if alt.id in alt_ver4:
                alt_ver4[alt.id].evidence = [
                    r for r in alt_ver4[alt.id].evidence if r.record_id not in bad_set
                ]
        if alt.discrimination_version == "v4" or exp_txt:
            raw_d = alt.model_dump()
            # Preserve legacy v3 ungrounded discrimination only when neither discrimination_version=='v4' nor control_span/experiment_text requires re-grounding
            if alt.discrimination_version == "v4" or alt.control_span or alt.target_engagement_span or alt.loophole:
                if not alt.loophole_ruled_out_why and alt.discrimination_version != "v4" and not alt.loophole:
                    # Legacy v3 alternative with clean control_span and empty loophole: supply distinct preds / ruled_out_why if already grounded
                    raw_d.setdefault("loophole_ruled_out_why", "addressed by explicit control_span" if alt.control_span else "")
                g_d = alternatives_v3.ground_discrimination_v4(raw_d, exp_txt, precision_status=prec_status)
                alt = ProposedAlternative.model_validate(g_d)
        grounded_alts.append(alt)
    c4.proposed_alternatives = grounded_alts

    return c4, cvs4, alt_ver4, routed_pmids, bg_refuted


def evaluate(
    card: HypothesisCard,
    ver_claims: list[ClaimVerification],
    alt_verifications: Optional[dict[str, ClaimVerification]] = None,
    *,
    implementation: Optional[dict] = None,
    as_of: str = "",
    experiment_text: str = "",
) -> V4Result:
    """Evaluate one hypothesis under Method v4.0 (`V4Result`)."""
    c4, cvs4, alt_ver4, routed_pmids, bg_refuted = prepare_for_v4(
        card, ver_claims, alt_verifications, experiment_text=experiment_text
    )
    base = r32.evaluate(c4, cvs4, alt_ver4, v36=True)
    gate = base.gate
    gate_reason = "" if gate == "pass" else "refuted_chain"
    if bg_refuted and gate == "pass":
        gate = "filtered"
        gate_reason = "refuted_background"

    # Build chain summary over the original role labels using filtered cvs4
    orig_card_copy = copy.deepcopy(card)
    for cl in orig_card_copy.claims:
        if "novel_contribution" in r32._claim_roles(cl) and not _is_pure_background(cl):
            cl.required_for_balance = True
    chain_sum = r32.diagnostic_chain_summary(orig_card_copy, cvs4, res=base)
    if bg_refuted:
        chain_sum["background_gate"]["gate_ok"] = False

    ck_diag = threats.checklist_diagnostic(c4, parse_preclinical=True)
    feas_score = v3_extra.feasibility(c4, as_of, implementation)
    feas_diag = v3_extra.feasibility_diagnostic(c4, as_of, implementation)

    return V4Result(
        method_version="v4.0",
        gate=gate,
        gate_reason=gate_reason,
        P=base.P,
        P_lo=base.P_lo,
        P_hi=base.P_hi,
        I=base.I,
        headroom_I=base.headroom_I,
        V=round(base.P * base.I, 6) if gate == "pass" else 0.0,
        scope=base.scope,
        chain_state=base.chain_state,
        support_share=base.support_share,
        coverage=base.coverage,
        coverage_counts=base.coverage_counts,
        weakest=base.weakest,
        links=base.links,
        chain_summary=chain_sum,
        checklist=ck_diag,
        worst_domain_risk=ck_diag.get("worst_domain_risk", "unknown"),
        resource_tier=feas_diag["resource_tier"],
        feasibility=feas_score,
        execution_readiness=feas_diag["execution_readiness"],
        routed_contradicting_alt_pmids=routed_pmids,
    )

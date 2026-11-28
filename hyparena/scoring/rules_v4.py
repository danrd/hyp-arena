"""Method v4.2 scorer and evaluator (`v4.2`, adopted 2026-11-28).

Core architectural principles (`Method v4.2`):
  1. Hard gate ONLY from proven findings:
     - `gate = 'filtered'` triggers strictly on proven top-design refutations (`refuted_chain`,
       `refuted_background`) or proven irreversible safety risk in living humans (`unsafe_protocol`).
     - Unverified / missing components (`insufficient` readiness, `searched_empty` links) NEVER
       filter a hypothesis out of rankings; instead they incur localized uncertainty fees so
       stronger aspects of a hypothesis still differentiate it.
  2. Relation-to-claim enforcement (`verify_claim/v23` + adjacent mechanism & organismal outcome priors):
     - Applies `verifier.enforce_relation_to_claim(rec, claim)` (preserving `direct_contradiction`
       on prepared between-group records with verbatim quotes, `M6`).
     - Intermediate `mechanism` claims admit verified `relation_to_claim == 'related'` supporting
       records at `0.5x` adjacent context without demoting novelty `N`.
     - `outcome` claims additionally admit verified intact-organism `related` prior trials
       (excluding cell/slice/review records, upstream-duplicated papers, and AE-only safety quotes)
       at `0.5x` adjacent context (`context_v34`) AND pass them to `novelty_v34` so prior trials in
       adjacent cohorts/species/classes map accurately to `new_context` / `translation` / `analog`.
  3. Localized uncertainty fees on `I`, `feasibility`, and `novelty`:
     - Translational `I` fee: `0.5x` for non-human experiments on human claims, `0.75x` for
       `human ex vivo` `prerequisite` (`0.5x` for `unclear`).
     - Model/assay readiness uncertainty fee on `I`: `UNOBTAINABLE_MODEL_I_FACTOR = 0.25` when
       `population_or_model` is `'insufficient'` (retaining discrimination differences across designs
       rather than collapsing `I` to `0.0`), and `0.5x` when delivery/assay is `'insufficient'`.
     - Novelty uncertainty cap (`cap_novelty_v4`): when `population_or_model == 'insufficient'`,
       `new_link` is capped at `new_combination` so unverified models cannot top `Frontier` by emptiness.
     - Feasibility uncertainty fee (`v3_extra.feasibility(..., claim_aligned=True)`): human-claim
       prerequisites pay `PRECLINICAL_SCALE_FEE = 0.5` on proxy `duration` and `sample_size`
       (alongside `sys_score = 0.0`), and unverified readiness applies `0.5 + 0.5 * readiness`.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Optional

from hyparena import METHOD_V4_VERSION
from hyparena.alternatives import alternatives_v3, threats
from hyparena.card.models import Claim, ClaimVerification, EvidenceRecord, HypothesisCard, ProposedAlternative
from hyparena.novelty.novelty_v34 import novelty as _novelty_v34
from hyparena.reading import verifier
from hyparena.scoring import rules_v3 as r3, rules_v32 as r32, v3_extra

TRANSLATIONAL_PREREQ_I_FACTOR = 0.5
EX_VIVO_PREREQ_I_FACTOR = 0.75
UNCLEAR_SCOPE_I_FACTOR = 0.5
UNOBTAINABLE_MODEL_I_FACTOR = 0.25
UNVALIDATED_COMPONENT_I_FACTOR = 0.5

_EFFICACY_CUES = (
    "improv", "reduc", "increas", "decreas", "enhanc", "restor", "lower", "rais",
    "change", "score", "threshold", "visual", "walk", "memory", "pain", "urgency", "fatigue",
)


@dataclass
class V4Result:
    method_version: str = METHOD_V4_VERSION
    gate: str = "pass"
    gate_reason: str = ""
    P: float = 0.0
    P_lo: float = 0.0
    P_hi: float = 0.0
    I: float = 0.0
    raw_I: float = 0.0
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


def _is_intermediate_mechanism(cl: Claim) -> bool:
    """True when `cl` is an intermediate causal mechanism step (not background, novel_contribution, or outcome)."""
    if _is_pure_background(cl):
        return False
    if cl.role == "outcome" or cl.link == "outcome":
        return False
    roles = r32._claim_roles(cl)
    if "outcome" in roles or "novel_contribution" in roles:
        return False
    return ("mechanism" in roles) or (cl.role == "mechanism")


def _is_organismal_outcome_prior(rec: EvidenceRecord, upstream_pmids: set[str]) -> bool:
    """True when a `related` supporting record on an `outcome` claim represents an intact-organism
    clinical or animal outcome trial (e.g. same drug in a broader cohort or same-class trial) rather
    than an upstream cell/slice assay, review, or adverse-event-only safety note.
    """
    if rec.record_id in upstream_pmids:
        return False
    if r3.record_design(rec) in ("cells", "review", "other"):
        return False
    if rec.outcome_match == "other":
        return False
    im = (rec.qualifiers_match or {}).get("intervention_match")
    if im in ("no", "different", "none"):
        return False
    ql = (rec.quote or "").lower()
    if "adverse event" in ql and not any(w in ql for w in _EFFICACY_CUES):
        return False
    return True


def _filter_records_v4(
    recs: list[EvidenceRecord],
    claim: Claim,
    *,
    against: bool,
    upstream_pmids: Optional[set[str]] = None,
) -> list[EvidenceRecord]:
    out: list[EvidenceRecord] = []
    is_mech = (not against) and _is_intermediate_mechanism(claim)
    is_out = (not against) and (claim.role == "outcome" or claim.link == "outcome")
    up_set = upstream_pmids or set()
    for rec in recs:
        guarded = verifier.enforce_relation_to_claim(rec, claim)
        rel = guarded.relation_to_claim
        if rel is None:
            out.append(guarded)
        elif not against and rel == "direct_support":
            out.append(guarded)
        elif is_mech and rel == "related":
            im = (guarded.qualifiers_match or {}).get("intervention_match")
            if im not in ("no", "different", "none") and guarded.outcome_match != "other":
                out.append(guarded)
        elif is_out and rel == "related":
            if _is_organismal_outcome_prior(guarded, up_set):
                out.append(guarded)
        elif against and rel == "direct_contradiction":
            out.append(guarded)
    return out


def has_unobtainable_model(implementation: Optional[dict]) -> bool:
    if not isinstance(implementation, dict) or not implementation.get("component_checks"):
        return False
    return any(
        isinstance(cc, dict)
        and str(cc.get("component") or "").lower() in ("population_or_model", "system_or_population_fit")
        and str(cc.get("evidence_status") or "").lower() == "insufficient"
        for cc in implementation["component_checks"]
    )


def cap_novelty_v4(
    card_v4: HypothesisCard,
    cvs_v4: list[ClaimVerification],
    base_v32: Optional[r32.V32Result] = None,
    *,
    implementation: Optional[dict] = None,
    absence: Optional[dict] = None,
    paper_outcomes: Optional[list[dict]] = None,
) -> Optional[str]:
    """Compute Method v4.2 novelty `N`, capping `new_link -> new_combination` when the experimental
    model/population itself is unverified (`population_or_model == 'insufficient'`).
    """
    nov = _novelty_v34(card_v4, cvs_v4, base_v32, absence=absence, paper_outcomes=paper_outcomes)
    if nov == "new_link" and has_unobtainable_model(implementation):
        return "new_combination"
    return nov


def _align_informativeness_v42(
    raw_i: float,
    card_raw: HypothesisCard,
    card_v4: HypothesisCard,
    implementation: Optional[dict] = None,
    source_text: str = "",
) -> float:
    """Apply translational scope and readiness uncertainty fees to `I` (`Method v4.2`)."""
    i_val = raw_i
    human_cl = v3_extra.claim_is_human(card_raw, source_text)
    ex_vivo = v3_extra.is_human_ex_vivo(card_v4, implementation)
    sys_name = str(card_v4.decisive_experiment.system or "unknown").lower()
    t_scope = getattr(card_v4.decisive_experiment, "tested_scope", None)

    if human_cl and sys_name not in ("human", "unknown"):
        i_val = round(i_val * TRANSLATIONAL_PREREQ_I_FACTOR, 4)
    elif human_cl and ex_vivo and t_scope == "prerequisite":
        i_val = round(i_val * EX_VIVO_PREREQ_I_FACTOR, 4)
    elif t_scope == "unclear":
        i_val = round(i_val * UNCLEAR_SCOPE_I_FACTOR, 4)

    if isinstance(implementation, dict) and implementation.get("component_checks"):
        min_r = float(
            implementation.get("min_readiness_score")
            if implementation.get("min_readiness_score") is not None
            else 1.0
        )
        if has_unobtainable_model(implementation):
            i_val = round(i_val * UNOBTAINABLE_MODEL_I_FACTOR, 4)
        elif min_r <= 0.0:
            i_val = round(i_val * UNVALIDATED_COMPONENT_I_FACTOR, 4)
    return i_val


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

    upstream_pmids = {
        r.record_id
        for cv in ver_claims
        for cl in [by_claim_id.get(cv.id)]
        if cl is not None and not _is_pure_background(cl) and cl.role != "outcome" and cl.link != "outcome"
        for r in (cv.evidence + cv.counterevidence)
    }

    # 1. Enforce v23 relation_to_claim guard on every claim verification
    cvs4: list[ClaimVerification] = []
    for cv in ver_claims:
        cv_copy = copy.deepcopy(cv)
        cl = by_claim_id.get(cv_copy.id) or cv_copy.claim or Claim(
            id=cv_copy.id, subject="intervention", relation="other", object="outcome"
        )
        cv_copy.evidence = _filter_records_v4(cv_copy.evidence, cl, against=False, upstream_pmids=upstream_pmids)
        cv_copy.counterevidence = _filter_records_v4(cv_copy.counterevidence, cl, against=True, upstream_pmids=upstream_pmids)
        cvs4.append(cv_copy)

    # 2. Fold pure background claims into a single gate check, ensure novel_contribution claims are required,
    #    and enforce the human outcome bridge when a human claim proposes a non-human experiment
    bg_refuted = False
    cross_species_human = (
        v3_extra.claim_is_human(card, experiment_text)
        and str(c4.decisive_experiment.system or "unknown").lower() not in ("human", "unknown")
    )
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
                cl.part = "premise"
                cl.link = None
            else:
                if "novel_contribution" in roles:
                    cl.required_for_balance = True
                if cross_species_human and (cl.role == "outcome" or cl.link == "outcome"):
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
            if alt.discrimination_version == "v4" or alt.control_span or alt.target_engagement_span or alt.loophole:
                if not alt.loophole_ruled_out_why and alt.discrimination_version != "v4" and not alt.loophole:
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
    """Evaluate one hypothesis under Method v4.2 (`V4Result`)."""
    c4, cvs4, alt_ver4, routed_pmids, bg_refuted = prepare_for_v4(
        card, ver_claims, alt_verifications, experiment_text=experiment_text
    )
    base = r32.evaluate(c4, cvs4, alt_ver4, v36=True)
    gate = base.gate
    gate_reason = "" if gate == "pass" else "refuted_chain"
    if bg_refuted and gate == "pass":
        gate = "filtered"
        gate_reason = "refuted_background"

    sys_name = str(c4.decisive_experiment.system or "").lower()
    ex_vivo = v3_extra.is_human_ex_vivo(c4, implementation)
    s_flags = v3_extra.collect_safety_flags(c4, implementation)
    if gate == "pass" and sys_name == "human" and not ex_vivo and "irreversible_no_ltfu" in s_flags:
        gate = "filtered"
        gate_reason = "unsafe_protocol"

    aligned_i = _align_informativeness_v42(
        base.I, card, c4, implementation=implementation, source_text=experiment_text
    )

    orig_card_copy = copy.deepcopy(card)
    cross_species_human = v3_extra.claim_is_human(card, experiment_text) and sys_name not in ("human", "unknown")
    for cl in orig_card_copy.claims:
        if not _is_pure_background(cl):
            if "novel_contribution" in r32._claim_roles(cl):
                cl.required_for_balance = True
            if cross_species_human and (cl.role == "outcome" or cl.link == "outcome"):
                cl.required_for_balance = True
    chain_sum = r32.diagnostic_chain_summary(orig_card_copy, cvs4, res=base)
    if bg_refuted:
        chain_sum["background_gate"]["gate_ok"] = False

    ck_diag = threats.checklist_diagnostic(c4, parse_preclinical=True)
    feas_score = v3_extra.feasibility(
        c4, as_of, implementation, claim_aligned=True, experiment_text=experiment_text
    )
    feas_diag = v3_extra.feasibility_diagnostic(c4, as_of, implementation)
    r_sc, r_rsn = v3_extra.safety_readiness_cap(
        c4,
        feas_diag["execution_readiness"]["readiness_score"],
        feas_diag["execution_readiness"]["readiness_reason"],
        implementation,
        experiment_text,
    )
    feas_diag["execution_readiness"]["readiness_score"] = round(r_sc, 3) if r_sc is not None else None
    feas_diag["execution_readiness"]["readiness_reason"] = r_rsn

    return V4Result(
        method_version=METHOD_V4_VERSION,
        gate=gate,
        gate_reason=gate_reason,
        P=base.P,
        P_lo=base.P_lo,
        P_hi=base.P_hi,
        I=aligned_i,
        raw_I=base.I,
        headroom_I=base.headroom_I,
        V=round(base.P * aligned_i, 6) if gate == "pass" else 0.0,
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

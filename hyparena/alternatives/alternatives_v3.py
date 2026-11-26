"""Method v3: alternatives proposed by a model (archive/docs/spec/method-v3.md, section 4).

One call per hypothesis (prompt propose_alternatives/v1) over the abstracts already read for it, dated by T. Code keeps only
support PMIDs from that list (an alternative without them weighs nothing in the rules), drops an alternative eliminated by
both outcomes, and keeps at most 5. The support of each alternative is checked by the verifier like a claim (rules, step 3).
"""
from __future__ import annotations

import typing
from typing import Optional

from hyparena.card.llm import ask
from hyparena.alternatives.informativeness import _norm
from hyparena.alternatives.threats import is_methodological
from hyparena.card.models import HypothesisCard, ProposedAlternative, Relation
from hyparena.scoring.rules_v32 import THREAT_CHECKLIST

MAX_ALTERNATIVES = 5
MAX_ABSTRACTS = 25
GROUNDED_VERSION = "v3"


def _experiment(card: HypothesisCard) -> str:
    e = card.decisive_experiment
    parts = [f"system {e.system}", f"design {e.design}", f"control {e.control}",
             f"n {e.n_planned}" if e.n_planned else "", f"primary outcome {e.primary_outcome}", f"endpoint {e.endpoint}",
             f"duration {e.duration_class}"]
    return ", ".join(p for p in parts if p and not p.endswith("unknown") and not p.endswith("None"))


def ground_discrimination(
    raw: dict,
    experiment_text: str,
    *,
    target_engagement_span: str = "",
    require_engagement_for_negative: bool = False,
) -> dict:
    """Constrain model verdicts using the recorded design; never ask the model to repair them.

    When `require_engagement_for_negative=True` (diagnostic calibration mode), credit on `on_negative`
    also requires a verbatim `target_engagement_span` grounded in `experiment_text`.
    """
    span = raw.get("control_span")
    span = span.strip() if isinstance(span, str) else ""
    grounded = bool(span) and _norm(span) in _norm(experiment_text)
    loophole = raw.get("loophole")
    if not isinstance(loophole, str):
        loophole = "The effect of the stated comparison on this explanation was not assessed."
    kind = raw.get("alt_kind")
    if kind not in ("positive_confounder", "negative_barrier"):
        kind = None
    required = raw.get("required_positive_result")
    required = required.strip() if isinstance(required, str) else ""
    positive, negative = raw.get("on_positive", "unchanged"), raw.get("on_negative", "unchanged")
    if not grounded:
        if positive == "eliminated":
            positive = "unchanged"
        if negative == "eliminated":
            negative = "unchanged"
    elif positive == "eliminated" and (loophole.strip() or kind is None):
        positive = "weakened"
    if kind != "negative_barrier" and not (kind == "positive_confounder" and grounded and required):
        negative = "unchanged"
    if require_engagement_for_negative and negative in ("eliminated", "weakened"):
        eng = (target_engagement_span or "").strip()
        if not (eng and _norm(eng) in _norm(experiment_text)):
            negative = "unchanged"
    if positive == negative == "eliminated":
        negative = "unchanged"
    return {**raw, "control_span": span if grounded else "", "loophole": loophole.strip(), "alt_kind": kind,
            "required_positive_result": required, "discrimination_version": GROUNDED_VERSION,
            "on_positive": positive, "on_negative": negative}


def screen_contradicting_pmids(raw: dict, ver_claims: list) -> dict:
    """Diagnostic check (evaluation-calibration-2026-11-25.md section 3):
    Identify whether any support_pmid of a proposed alternative already acts as direct counterevidence
    on a core claim of the card, so skeptical evidence is routed to claim counterarguments rather
    than inflating informativeness I.
    """
    raw_pmids = {str(p).replace("PMID:", "").strip() for p in (raw.get("support_pmids") or []) if str(p).strip()}
    direct_contra: dict[str, list[str]] = {}
    any_contra: dict[str, list[str]] = {}
    for cv in ver_claims or []:
        for rec in getattr(cv, "counterevidence", None) or []:
            pid = str(getattr(rec, "record_id", "") or "").replace("PMID:", "").strip()
            if pid and pid in raw_pmids:
                any_contra.setdefault(pid, []).append(cv.id)
                if getattr(rec, "relation_to_claim", None) in ("direct_contradiction", None):
                    direct_contra.setdefault(pid, []).append(cv.id)
    return {
        "support_pmids": sorted(raw_pmids),
        "contradicting_pmids": sorted(direct_contra),
        "contradicting_claims": direct_contra,
        "any_counterevidence_pmids": sorted(any_contra),
        "should_route_to_counterevidence": bool(direct_contra),
    }


def ground_discrimination_v4(
    raw: dict,
    experiment_text: str,
    *,
    precision_status: str = "missing",
) -> dict:
    """Method v4 deterministic grounding for competing alternatives and multi-contrast nulls:
    1. Requires verbatim `control_span` in `experiment_text` for any credit (`weakened`/`eliminated`).
    2. `on_positive == 'eliminated'` requires distinct `prediction_hypothesis` vs `prediction_alternative`,
       empty `loophole`, AND non-empty `loophole_ruled_out_why`; otherwise capped at `'weakened'`.
    3. Unconditional `on_negative` credit (`weakened`/`eliminated`) requires BOTH a verbatim
       `target_engagement_span` grounded in `experiment_text` AND `precision_status == 'stated_for_contrast'`;
       when engagement is grounded and the null contradicts `prediction_alternative` (or `conditional_on_negative`
       is set) while precision is missing/general, preserves the conditional verdict in `conditional_on_negative`
       and sets unconditional `on_negative = 'unchanged'`.
    """
    norm_exp = _norm(experiment_text or "")
    cspan = (raw.get("control_span") or "").strip() if isinstance(raw.get("control_span"), str) else ""
    ctrl_grounded = bool(cspan) and _norm(cspan) in norm_exp

    espan = (raw.get("target_engagement_span") or "").strip() if isinstance(raw.get("target_engagement_span"), str) else ""
    eng_grounded = bool(espan) and _norm(espan) in norm_exp

    loophole = (raw.get("loophole") or "").strip() if isinstance(raw.get("loophole"), str) else ""
    ruled_out_why = (raw.get("loophole_ruled_out_why") or "").strip() if isinstance(raw.get("loophole_ruled_out_why"), str) else ""
    pred_h = (raw.get("prediction_hypothesis") or "").strip() if isinstance(raw.get("prediction_hypothesis"), str) else ""
    pred_a = (raw.get("prediction_alternative") or "").strip() if isinstance(raw.get("prediction_alternative"), str) else ""
    distinct_preds = bool(pred_h and pred_a and _norm(pred_h) != _norm(pred_a))

    pos = str(raw.get("on_positive") or "unchanged").strip()
    neg = str(raw.get("on_negative") or "unchanged").strip()
    cond_neg = str(raw.get("conditional_on_negative") or neg or "unchanged").strip()
    if pos not in ("eliminated", "weakened", "unchanged"):
        pos = "unchanged"
    if neg not in ("eliminated", "weakened", "unchanged"):
        neg = "unchanged"
    if cond_neg not in ("eliminated", "weakened", "unchanged"):
        cond_neg = "unchanged"

    if not ctrl_grounded:
        pos = "unchanged"
        neg = "unchanged"
    else:
        if pos == "eliminated":
            if loophole or not ruled_out_why or not distinct_preds:
                pos = "weakened"
        if neg in ("eliminated", "weakened"):
            if not eng_grounded or precision_status != "stated_for_contrast":
                neg = "unchanged"

    if cond_neg in ("eliminated", "weakened") and not eng_grounded:
        cond_neg = "unchanged"

    if pos == neg == "eliminated":
        neg = "unchanged"

    return {
        **raw,
        "control_span": cspan if ctrl_grounded else "",
        "target_engagement_span": espan if eng_grounded else "",
        "loophole": loophole,
        "loophole_ruled_out_why": ruled_out_why,
        "on_positive": pos,
        "on_negative": neg,
        "conditional_on_negative": cond_neg,
        "precision_status_used": precision_status,
    }


def propose(client, family: str, card: HypothesisCard, abstracts: dict[str, dict], as_of: Optional[str],
            avoid=frozenset(), log: Optional[list] = None, version: str = "v1",
            registry_text: str = "") -> list[ProposedAlternative]:
    """`abstracts`: PMID -> {title, abstract, year} of the papers read for this hypothesis (already dated by T)."""
    allowed = {str(p) for p in abstracts}
    items = [{"pmid": p, "year": a.get("year", ""), "title": a.get("title", ""), "abstract": a.get("abstract", "")[:1500]}
             for p, a in list(abstracts.items())[:MAX_ABSTRACTS]]
    chain = [c for c in card.claims if c.link or c.role in ("outcome", "mechanism", "premise")]
    experiment_text = registry_text or card.decisive_experiment.span
    variables = {"as_of": as_of or "today", "claim_plain": card.claim_plain, "chain": chain, "experiment": _experiment(card) or "not stated",
                 "abstracts": items, "relations": ", ".join(typing.get_args(Relation)),
                 "registry_text": experiment_text if version == GROUNDED_VERSION else registry_text}

    def validate(v):
        alts = v.get("alternatives")
        return [] if isinstance(alts, list) else ['the reply must be an object with an "alternatives" list']
    value, _ = ask(client, role="propose_alternatives", family=family, template="propose_alternatives", version=version,
                   variables=variables, validate=validate, rounds=2, avoid=avoid, log=log)
    out: list[ProposedAlternative] = []
    for i, raw in enumerate((value or {}).get("alternatives") or [], start=1):
        if not isinstance(raw, dict) or len(out) >= MAX_ALTERNATIVES:
            continue
        raw = {**raw, "id": f"p{i}", "support_pmids": [str(p).replace("PMID:", "").strip() for p in raw.get("support_pmids") or []
                                                     if str(p).replace("PMID:", "").strip() in allowed]}
        if raw.get("relation") not in typing.get_args(Relation):
            raw["relation"] = "other"
        if version == GROUNDED_VERSION:
            raw = ground_discrimination(raw, experiment_text)
        try:
            alt = ProposedAlternative.model_validate(raw)
        except Exception:                                   # eliminated by both outcomes, or malformed: dropped
            continue
        if THREAT_CHECKLIST and is_methodological(alt):    # v3.11: judged by the threat checklist from the design
            continue
        out.append(alt)
    return out

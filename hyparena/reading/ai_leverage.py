"""Method v4.2 bottleneck-bound AI leverage (`ai_leverage`, mapped onto `SPECS['ai_role']`).

Replaces literal `"AI"` buzzword matching with a two-stage anti-decorative evaluator:
  1. Deterministic code pre-filter (`eligible_bottleneck_modes`):
     - `"analysis"` (`signal_or_stratification`): eligible only when the experiment or mechanism
       involves high-dimensional waveforms, imaging, spatial/optical mapping, multi-omics, or
       continuous multi-channel telemetry (blocked on standard pill + scalar clinical score RCTs).
     - `"in_the_loop"` (`closed_loop_control`): eligible only when the intervention involves
       programmable / time-varying stimulation, pacing, field delivery, or adaptive titration.
     - `"intervention"` (`agent_or_construct_design`): eligible only when the intervention involves
       engineered genetic constructs (plasmid/vector/capsid/promoter/ASO/siRNA), de novo biologics/
       peptides, or a direct patient-facing digital/AI agent (blocked on known small molecules).
     When `eligible_bottleneck_modes` is empty, returns `"none"` deterministically with 0 LLM calls.
  2. Single-model bottleneck check (`assess`, `prompts/ai_leverage/v1.j2`) + deterministic code
     verification (`validate_ai_leverage`):
     - Clamps model output to `eligible_modes | {"none"}`.
     - Verifies that `bottleneck_span` appears verbatim in the hypothesis/experiment text and that
       `validation_metric` and `why_non_decorative` are non-empty; otherwise downgrades to `"none"`.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from hyparena.card.models import HypothesisCard
from hyparena.llm.prompts import render
from hyparena.reading.verifier import _norm, parse_records

TEMPLATE_VERSION = "v1"
LEVELS = ("none", "analysis", "in_the_loop", "intervention")
MODE_TO_LEVEL = {
    "none": "none",
    "signal_or_stratification": "analysis",
    "analysis": "analysis",
    "closed_loop_control": "in_the_loop",
    "in_the_loop": "in_the_loop",
    "agent_or_construct_design": "intervention",
    "intervention": "intervention",
}
LEVEL_TO_MODE = {
    "none": "none",
    "analysis": "signal_or_stratification",
    "in_the_loop": "closed_loop_control",
    "intervention": "agent_or_construct_design",
}

HIGH_DIM_SIGNAL_TOKENS = (
    "waveform", "envelope-following", "evoked potential", "electroencephalog", "eeg",
    "electromyog", "emg", "optical mapping", "calcium transient", "patch-clamp", "patch clamp",
    "single-cell", "single cell", "rna-seq", "transcriptom", "proteom", "metabolom", "lipidom",
    "methylation", "epigenom", "microbiome", "metagenom", "oct ", "optical coherence",
    "mri", " neuroimaging", "tractography", "pet ", "spect ", "ultrasound", "doppler",
    "high-density", "continuous", "ambulatory", "telemetry", "wearable", "acceleromet",
    "actigraph", "urodynamic", "cystometr", "speech-in-noise", "audiometr", "microscop",
    "whole-slide", "histomorph", "spatial", "impedance spectroscop", "heart rate variability",
)

CLOSED_LOOP_ELIGIBLE_TOKENS = (
    "pulsat", "pulsed", "stimulation", "stimulator", "neuromodulat", "transdermal",
    "transcranial", "auricular", "vagus", "tacs", "tdcs", "tms", "acoustic", "sound",
    "electric field", "bioelectronic", "pacing", "pacemaker", "closed-loop", "closed loop",
    "adaptive", "feedback-controlled", "titrat", "programmable",
)

CONSTRUCT_OR_AGENT_TOKENS = (
    "plasmid", "vector", "aav", "lentivir", "mrna", "sirna", "shrna", "antisense", "aso",
    "crispr", "cas9", "base edit", "prime edit", "epigenetic reprogram", "promoter", "capsid",
    "chimeric", "car-t", "engineered", "de novo", "peptide", "aptamer", "nanobody", "antibody",
    "digital therapeutic", "cognitive agent", "conversational agent", "ai coach", "virtual agent",
)


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    val = parse_records(text)
    if isinstance(val, dict):
        return val
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def eligible_bottleneck_modes(
    card: HypothesisCard,
    experiment_text: str = "",
    implementation: Optional[dict] = None,
) -> set[str]:
    """Return the subset of `{'analysis', 'in_the_loop', 'intervention'}` structurally supported
    by the card's interventions and measurements (anti-decorative deterministic pre-filter).
    """
    de = card.decisive_experiment
    int_types = {str(i.type or "").lower() for i in card.pico.intervention}
    int_text = " ".join(
        f"{i.label or ''} {i.regimen or ''} {i.route or ''}" for i in card.pico.intervention
    ).lower()
    meas_text = " ".join(
        [
            de.primary_outcome or "",
            " ".join(de.primary_outcomes or []),
            de.span or "",
            de.target_engagement_span or "",
            card.pico.outcome.metric or "",
            " ".join(f"{c.subject.label} {c.object.label} {c.qualifiers.get('measure', '')}" for c in card.claims),
            experiment_text or "",
        ]
    ).lower()

    modes: set[str] = set()

    # 1. Construct / sequence / therapeutic AI agent design
    if (int_types & {"gene", "cell"}) or any(tok in int_text for tok in CONSTRUCT_OR_AGENT_TOKENS):
        modes.add("intervention")

    # 2. Closed-loop / adaptive physical, device, or dynamic-regimen control
    if (int_types & {"device", "exposure", "behavioural"}) or any(
        tok in int_text for tok in CLOSED_LOOP_ELIGIBLE_TOKENS
    ):
        if any(tok in (int_text + " " + (de.span or "").lower() + " " + (experiment_text or "").lower()) for tok in CLOSED_LOOP_ELIGIBLE_TOKENS):
            modes.add("in_the_loop")

    # 3. High-dimensional signal processing / phenotyping / responder stratification
    if any(tok in meas_text for tok in HIGH_DIM_SIGNAL_TOKENS) or de.system == "data_analysis":
        modes.add("analysis")

    return modes


def validate_ai_leverage(
    raw: Optional[dict],
    card: HypothesisCard,
    experiment_text: str = "",
    implementation: Optional[dict] = None,
) -> dict:
    """Validate and clamp `ai_leverage` output against `eligible_bottleneck_modes` and verbatim span check."""
    eligible = eligible_bottleneck_modes(card, experiment_text=experiment_text, implementation=implementation)
    if not eligible:
        return {
            "ai_role": "none",
            "bottleneck_mode": "none",
            "bottleneck_span": "",
            "why_non_decorative": "",
            "validation_metric": "",
            "eligible_modes": [],
            "verified": True,
            "issue": "ineligible_by_code_guard",
        }
    if not isinstance(raw, dict):
        return {
            "ai_role": "none",
            "bottleneck_mode": "none",
            "bottleneck_span": "",
            "why_non_decorative": "",
            "validation_metric": "",
            "eligible_modes": sorted(eligible),
            "verified": False,
            "issue": "unparsed",
        }

    raw_lv = str(raw.get("ai_leverage") or raw.get("ai_role") or "none").strip().lower()
    raw_mode = str(raw.get("bottleneck_mode") or "none").strip().lower()
    lv = MODE_TO_LEVEL.get(raw_lv) or MODE_TO_LEVEL.get(raw_mode) or "none"
    if lv == "none":
        return {
            "ai_role": "none",
            "bottleneck_mode": "none",
            "bottleneck_span": "",
            "why_non_decorative": str(raw.get("why_non_decorative") or "").strip(),
            "validation_metric": "",
            "eligible_modes": sorted(eligible),
            "verified": True,
            "issue": "",
        }

    issue = ""
    if lv not in eligible:
        # Downgrade to highest eligible mode only if compatible, otherwise "none"
        if lv == "in_the_loop" and "analysis" in eligible:
            lv = "analysis"
            issue = "clamped_to_eligible_analysis"
        else:
            return {
                "ai_role": "none",
                "bottleneck_mode": "none",
                "bottleneck_span": "",
                "why_non_decorative": "",
                "validation_metric": "",
                "eligible_modes": sorted(eligible),
                "verified": False,
                "issue": f"mode_not_eligible:{lv}",
            }

    span = str(raw.get("bottleneck_span") or "").strip()
    why = str(raw.get("why_non_decorative") or "").strip()
    metric = str(raw.get("validation_metric") or "").strip()

    corpus = " \n ".join(
        [
            experiment_text or "",
            card.claim_plain or "",
            card.decisive_experiment.span or "",
            card.decisive_experiment.primary_outcome or "",
            " ".join(card.decisive_experiment.primary_outcomes or []),
            " ".join(i.span or i.label or "" for i in card.pico.intervention),
            " ".join(c.source_span or "" for c in card.claims),
        ]
    )
    span_norm = _norm(span)
    if len(span_norm) < 10 or span_norm not in _norm(corpus):
        return {
            "ai_role": "none",
            "bottleneck_mode": "none",
            "bottleneck_span": "",
            "why_non_decorative": "",
            "validation_metric": "",
            "eligible_modes": sorted(eligible),
            "verified": False,
            "issue": "unverified_bottleneck_span",
        }
    if len(_norm(why)) < 10 or len(_norm(metric)) < 5:
        return {
            "ai_role": "none",
            "bottleneck_mode": "none",
            "bottleneck_span": "",
            "why_non_decorative": "",
            "validation_metric": "",
            "eligible_modes": sorted(eligible),
            "verified": False,
            "issue": "missing_metric_or_rationale",
        }

    return {
        "ai_role": lv,
        "bottleneck_mode": LEVEL_TO_MODE[lv],
        "bottleneck_span": span,
        "why_non_decorative": why,
        "validation_metric": metric,
        "eligible_modes": sorted(eligible),
        "verified": True,
        "issue": issue,
    }


def heuristic_ai_leverage(
    card: HypothesisCard,
    experiment_text: str = "",
    implementation: Optional[dict] = None,
) -> dict:
    """Offline deterministic fallback (`0` LLM calls) when evaluating saved runs without an API client:
    assigns a bottleneck-bound `ai_role` ONLY when both structural eligibility AND a verbatim
    bottleneck phrase in `experiment_text` / `card` are present, validated through `validate_ai_leverage`.
    """
    # Honour explicit author-anchored ai_role first if it passes eligibility
    eligible = eligible_bottleneck_modes(card, experiment_text=experiment_text, implementation=implementation)
    if not eligible:
        return validate_ai_leverage(None, card, experiment_text=experiment_text, implementation=implementation)

    if card.ai_role != "none" and card.ai_role in eligible and (card.ai_role_span or "").strip():
        cand = {
            "ai_leverage": card.ai_role,
            "bottleneck_mode": LEVEL_TO_MODE[card.ai_role],
            "bottleneck_span": card.ai_role_span,
            "why_non_decorative": "Explicitly anchored AI bottleneck in protocol text.",
            "validation_metric": "Out-of-sample performance on primary endpoint contrast.",
        }
        res = validate_ai_leverage(cand, card, experiment_text=experiment_text, implementation=implementation)
        if res["ai_role"] != "none":
            return res

    # Otherwise inspect verbatim spans in order: intervention -> in_the_loop -> analysis
    de = card.decisive_experiment
    candidate_spans = [
        *(i.span or i.label for i in card.pico.intervention),
        de.target_engagement_span or "",
        de.primary_outcome or "",
        *(de.primary_outcomes or []),
        de.span or "",
    ]
    # Also split sentences from experiment_text
    if experiment_text:
        candidate_spans.extend(s.strip() for s in re.split(r"(?<=[.;])\s+|\n+", experiment_text) if 15 <= len(s.strip()) <= 220)

    def _find_span(tokens: tuple[str, ...]) -> str:
        for sp in candidate_spans:
            s = (sp or "").strip()
            if 15 <= len(s) <= 240 and any(tok in s.lower() for tok in tokens):
                return s
        return ""

    if "intervention" in eligible:
        sp = _find_span(CONSTRUCT_OR_AGENT_TOKENS)
        if sp:
            return validate_ai_leverage(
                {
                    "ai_leverage": "intervention",
                    "bottleneck_mode": "agent_or_construct_design",
                    "bottleneck_span": sp,
                    "why_non_decorative": "Sequence/construct or therapeutic-agent design space exceeds manual single-variant selection.",
                    "validation_metric": "Target expression/engagement potency vs off-target profile across construct variants.",
                },
                card,
                experiment_text=experiment_text,
                implementation=implementation,
            )

    if "in_the_loop" in eligible:
        # Require both programmable stimulation AND physiological feedback/monitoring readout
        sp = _find_span(CLOSED_LOOP_ELIGIBLE_TOKENS)
        sig_sp = _find_span(HIGH_DIM_SIGNAL_TOKENS)
        if sp and sig_sp:
            return validate_ai_leverage(
                {
                    "ai_leverage": "in_the_loop",
                    "bottleneck_mode": "closed_loop_control",
                    "bottleneck_span": sp,
                    "why_non_decorative": "Programmable stimulation/field parameters interact with time-varying tissue state measured by continuous biosignals.",
                    "validation_metric": "Closed-loop state-adapted delivery vs fixed open-loop stimulation on target engagement.",
                },
                card,
                experiment_text=experiment_text,
                implementation=implementation,
            )

    if "analysis" in eligible:
        sp = _find_span(HIGH_DIM_SIGNAL_TOKENS)
        if sp:
            return validate_ai_leverage(
                {
                    "ai_leverage": "analysis",
                    "bottleneck_mode": "signal_or_stratification",
                    "bottleneck_span": sp,
                    "why_non_decorative": "High-dimensional waveform, imaging, spatial, or multi-channel physiological readout benefits from learned signal extraction or responder stratification.",
                    "validation_metric": "Cross-validated signal-to-noise / responder AUROC vs single scalar summary feature.",
                },
                card,
                experiment_text=experiment_text,
                implementation=implementation,
            )

    return validate_ai_leverage({"ai_leverage": "none"}, card, experiment_text=experiment_text, implementation=implementation)


def assess(
    client,
    card: HypothesisCard,
    experiment_text: str = "",
    implementation: Optional[dict] = None,
    *,
    avoid: frozenset[str] = frozenset(),
    family: Optional[str] = None,
    log: Optional[list] = None,
) -> dict:
    """Single-model bottleneck-bound `ai_leverage` assessment (`Method v4.2`)."""
    eligible = eligible_bottleneck_modes(card, experiment_text=experiment_text, implementation=implementation)
    if not eligible:
        return validate_ai_leverage(None, card, experiment_text=experiment_text, implementation=implementation)

    chosen_family = family
    if not chosen_family:
        fams = [f for f in getattr(client, "families", lambda: [])() if f not in avoid] if callable(getattr(client, "families", None)) else []
        chosen_family = "deepseek" if "deepseek" in fams else (fams[0] if fams else None)
    if not chosen_family:
        return heuristic_ai_leverage(card, experiment_text=experiment_text, implementation=implementation)

    de = card.decisive_experiment
    exp_summary = (
        f"system={de.system}, design={de.design}, control={de.control}, "
        f"endpoint={de.endpoint}, duration={de.duration_class}, n={de.n_planned}"
    )
    pop = card.pico.population
    prompt = render(
        "ai_leverage",
        TEMPLATE_VERSION,
        claim=card.claim_plain,
        population=f"{pop.label} ({pop.condition})",
        interventions="; ".join(f"{i.label} (type={i.type}, route={i.route}, regimen={i.regimen})" for i in card.pico.intervention),
        primary_outcome=de.primary_outcome or card.pico.outcome.metric,
        exp_summary=exp_summary,
        eligible_modes=", ".join(sorted(eligible)),
        exp_text=(experiment_text or de.span or "")[:2500],
    )
    reply = client.call(role="verify_claim", family=chosen_family, prompt=prompt)
    checked = validate_ai_leverage(
        _parse_json(reply.text),
        card,
        experiment_text=experiment_text,
        implementation=implementation,
    )
    if log is not None:
        log.append(
            {
                "kind": "llm",
                "template": f"ai_leverage/{TEMPLATE_VERSION}",
                "role": "verify_claim",
                "family": chosen_family,
                "ai_role": checked["ai_role"],
                "bottleneck_mode": checked["bottleneck_mode"],
                "issue": checked["issue"],
                "tokens_in": getattr(reply, "tokens_in", 0),
                "tokens_out": getattr(reply, "tokens_out", 0),
                "seconds": getattr(reply, "seconds", 0.0),
                "error": getattr(reply, "error", None),
            }
        )
    return checked

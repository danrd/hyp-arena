"""Methodological threats judged from the stated design (method v3.11; specs/alternatives/threat-checklist-2026-11-16.yaml).

A methodological alternative (practice on the test, regression to the mean, the assessor's or the participant's knowledge
of the arm, unequal attention, selection, co-interventions, multiplicity) is not a competing cause in the world but an
artefact of how the experiment is run. Risk-of-bias tools judge such threats from the design, without a literature
search: RoB 2 (Sterne 2019, PMID 31462531), ROBINS-I (Sterne 2016, PMID 27733354), SYRCLE (Hooijmans 2014, PMID 24667063).
So the proposer's methodological alternatives are dropped (`is_methodological`) and every experiment gets the fixed list
of threats of its system (`checklist`): in humans each threat is judged by code from the design; in animals, cells and
data analysis a yes/no feature does not carry the verdict (Argon pack 28: weighted kappa 0.07 for cells), so each threat
is "does not tell apart" with the feature that would rule it out named as an improvement.
"""
from __future__ import annotations

import re
from typing import Optional

from hyparena.card.models import HypothesisCard

# kinds of a proposed alternative by the words of its statement and rationale; the first that matches decides
KINDS = (
    ("multiplicity", r"multiple (comparisons|test|endpoint|primary)|multiplicity|family-wise|false-positive|statistical independence|independent observations"),
    ("practice", r"practice|familiari[sz]|learning effect|motor learning|test-retest|repeated (test|assess|measure)|retest"),
    ("regression", r"regression to the mean|natural (course|history|recovery)|spontaneous|secular|time trend|seasonal"),
    ("assessor", r"observer|assessor|rater|measurement bias|detection bias|ascertainment|unblinded (outcome|trainer|staff|physio|senior)|charting"),
    ("attention", r"\bcontact\b|attention|supervision|hawthorne|social interaction|staff time"),
    ("expectation", r"expectation|expectanc|placebo|nocebo|unblind|lack of (participant )?blinding|self-report|social desirability|volitional|motivation"),
    ("selection", r"selection|attrition|drop-?out|completers|baseline (imbalance|difference|between)|healthy[- ]user|survivor"),
    ("cointervention", r"adherence|compliance|co-?intervention|concomitant|snacking|carry-?over|washout|vehicle|usual care (drift|change)"),
)

THREATS = {
    "human": ("practice", "regression", "assessor", "expectation", "attention", "selection", "cointervention", "multiplicity"),
    "animal": ("allocation", "assessor", "attrition", "handling", "housing", "sex_strain_age", "multiplicity"),
    "cells": ("batch", "off_target", "vehicle", "culture_artefact", "line_identity", "multiplicity"),
    "data_analysis": ("confounding", "reverse_causation", "selection", "measurement", "multiplicity"),
}
SYSTEM = {"human": "human", "mouse": "animal", "rat": "animal", "worm": "animal", "fly": "animal", "yeast": "cells",
          "cells": "cells", "in_vitro": "cells", "data_analysis": "data_analysis"}
VALUE = {"eliminated": 1.0, "weakened": 0.5, "unchanged": 0.0}
A_CHECKLIST = 0.5                     # the support the checklist counts with in I (one alternative of support 1/2)

# what would rule each threat out: the improvement item of a threat left standing
FIX = {
    "practice": "a randomised concurrent control group tested on the same schedule",
    "regression": "a randomised concurrent control group",
    "assessor": "outcome assessors masked to the group",
    "expectation": "masked participants and a placebo or sham control",
    "attention": "a placebo or sham control with the same contact time",
    "selection": "randomised allocation and an analysis of all randomised participants",
    "cointervention": "randomised allocation and co-interventions recorded in both groups",
    "multiplicity": "one pre-specified primary outcome and analysis",
    "allocation": "animals randomised to groups across cages and litters",
    "attrition": "every animal accounted for, with exclusions pre-specified",
    "handling": "controls handled and injected the same way (vehicle, sham procedure)",
    "housing": "groups housed under the same conditions, cages balanced across groups",
    "sex_strain_age": "both sexes, or a second strain or age",
    "batch": "independent replicates (donors, clones or batches), not passages of one culture",
    "off_target": "a specificity control: a second tool on the same target, a rescue, or a dose-response",
    "vehicle": "a vehicle control matched in concentration",
    "culture_artefact": "the finding repeated in primary cells or in vivo",
    "line_identity": "authenticated lines (STR profile) tested for mycoplasma",
    "confounding": "adjustment for the named confounders, or a design that removes them (siblings, Mendelian randomisation)",
    "reverse_causation": "exposure measured before the outcome, with a lag",
    "measurement": "a validated measure applied the same way in the groups compared",
}


def kind_of(text: str) -> Optional[str]:
    return next((k for k, rx in KINDS if re.search(rx, text, re.I)), None)


def is_methodological(alt) -> bool:
    """A proposed alternative whose statement or rationale names a methodological kind."""
    text = f"{alt.subject.label} {alt.relation} {alt.object.label}. {getattr(alt, 'rationale', '') or ''}"
    return kind_of(text) is not None


def human_verdict(kind: str, reg: dict) -> str:
    """What the stated design does to a threat in humans under the expected result, from the registry design fields
    (allocation, model, who is masked, arm types): specs/alternatives/design-rule-2026-11-16.yaml."""
    rand = reg.get("allocation") == "randomized"
    types = [a.get("type") for a in reg.get("arms") or []]
    control = len(types) >= 2 or reg.get("model") in ("parallel", "crossover", "factorial")
    masked = set(reg.get("masked") or [])
    dummy = any(t in ("placebo comparator", "sham comparator") for t in types)
    if kind in ("practice", "regression"):
        return "eliminated" if rand and control else "weakened" if control else "unchanged"
    if kind == "assessor":
        return "eliminated" if "outcomes assessor" in masked else "unchanged"
    if kind == "expectation":
        p = "participant" in masked
        return "eliminated" if p and dummy else "weakened" if p or dummy else "unchanged"
    if kind == "attention":
        return "eliminated" if dummy else "weakened" if "active comparator" in types else "unchanged"
    if kind in ("selection", "cointervention"):
        return "weakened" if rand else "unchanged"
    return "unchanged"


def design_fields(card: HypothesisCard) -> dict:
    """The registry design fields of the card when it has them, else its stated experiment (masking unknown = not masked)."""
    e = card.decisive_experiment
    reg = getattr(e, "registry", None) or {}
    if reg.get("allocation") in ("randomized", "non_randomized"):
        return reg
    ctrl = str(e.control or "unknown") not in ("unknown", "none", "")
    other = {"placebo": "placebo comparator", "sham": "sham comparator", "active": "active comparator"}.get(str(e.control), "other")
    return {"allocation": "randomized" if e.design == "rct" else "non_randomized", "model": "parallel" if ctrl else "single group",
            "masked": [], "arms": [{"type": "experimental"}, {"type": other}] if ctrl else [{"type": "experimental"}]}


def checklist(card: HypothesisCard) -> Optional[dict]:
    """{system, share, threats: {threat: verdict}, open: [{threat, fix}]}; None when the system is unknown (no experiment)."""
    system = SYSTEM.get(str(card.decisive_experiment.system))
    if system is None:
        return None
    f = design_fields(card) if system == "human" else {}
    v = {t: human_verdict(t, f) if system == "human" else "unchanged" for t in THREATS[system]}
    return {"system": system, "share": round(sum(VALUE[x] for x in v.values()) / len(v), 4), "threats": v,
            "open": [{"threat": t, "verdict": x, "fix": FIX[t]} for t, x in v.items() if x != "eliminated"]}


def worst_domain_risk(threats_map: dict[str, str]) -> str:
    """RoB 2 / ROBINS-I style worst-domain summary alongside the arithmetic checklist share.

    - Any 'unchanged' (unaddressed) threat -> 'high'
    - Two or more 'weakened' threats (multiple domains with some concerns) -> 'high'
    - Exactly one 'weakened' threat -> 'some_concerns'
    - All 'eliminated' -> 'low'
    """
    if not threats_map:
        return "not_applicable"
    vals = list(threats_map.values())
    if any(x == "unchanged" for x in vals):
        return "high"
    n_weak = sum(1 for x in vals if x == "weakened")
    if n_weak >= 2:
        return "high"
    if n_weak == 1:
        return "some_concerns"
    return "low"


_PRECLINICAL_PATTERNS: dict[str, tuple[str, str]] = {
    # (threat_kind -> (eliminated_regex, weakened_regex))
    "allocation": (r"\brandomi[sz](?:e|ed|ation)\b.*\b(?:litter|cage|block|stratifi)", r"\brandomi[sz](?:e|ed|ation)\b"),
    "assessor": (r"\b(?:blinded|masked)\b.*\b(?:assess|histolog|record|scor|evaluat|adjudicat|quantif)", r"\b(?:blinded|masked)\b"),
    "attrition": (r"\bpre-?specifi\w*\s+exclus|intent-?to-?treat|account\w*\s+for\s+all\s+animals", r"\battrition|dropout|exclusion"),
    "handling": (r"\b(?:sham|vehicle|isotype|matched\s+reporter|inactive\s+control)\b", r"\bcontrol\b"),
    "housing": (r"\b(?:co-?hous|cage\w*\s+balanc|same\s+housing|littermate)", r"\bhousing|cage"),
    "sex_strain_age": (r"\b(?:both\s+sexes|balanced\s+by\s+sex|male\s+and\s+female)\b", r"\b(?:aged|old|older)\b"),
    "batch": (r"\b(?:independent\s+(?:donor|isogenic|clone|batch)|paired\s+(?:donor|explant)|across\s+\w+\s+independent)\b", r"\breplicate|donor"),
    "off_target": (r"\b(?:add-?back|rescue|dose[-–]response|second\s+tool|reverse\s+polarity|isotype|inactive\s+control\s+peptide)\b", r"\btarget\s+engagement|verify\b"),
    "vehicle": (r"\b(?:vehicle|isotype|inactive\s+control|sham|reporter\s+vector)\b", r"\bcontrol\b"),
    "culture_artefact": (r"\b(?:explant|primary\s+cell|in\s+vivo|surgical\s+donor|human\s+cortical)\b", r"\bco-?culture|organoid"),
    "line_identity": (r"\b(?:STR\s+profil|mycoplasma|authenticated|isogenic)\b", r"\bpassage|low-passage"),
    "multiplicity": (r"\b(?:primary\s+endpoint|prespecif\w*\s+primary)\b", r"\bprimary\s+outcome"),
}


def preclinical_verdict(kind: str, text: str) -> str:
    """Experimental protocol-grounded verdict parser for animal and cell/explant designs."""
    if not (text or "").strip():
        return "unchanged"
    pats = _PRECLINICAL_PATTERNS.get(kind)
    if not pats:
        return "unchanged"
    strong_rx, weak_rx = pats
    if re.search(strong_rx, text, re.I):
        return "weakened"
    if re.search(weak_rx, text, re.I):
        return "weakened"
    return "unchanged"


def checklist_diagnostic(card: HypothesisCard, *, parse_preclinical: bool = True) -> Optional[dict]:
    """Diagnostic wrapper over checklist(card) adding RoB-2 worst_domain_risk and optional
    experimental parsing of explicit controls in animal/cell protocol spans.
    Does not alter v3.13 checklist(card) or I.
    """
    base = checklist(card)
    if base is None:
        return None
    system = base["system"]
    threats_map = dict(base["threats"])
    exp_text = card.decisive_experiment.span or ""
    used_preclinical = False
    if parse_preclinical and system in ("animal", "cells") and exp_text.strip():
        used_preclinical = True
        threats_map = {t: preclinical_verdict(t, exp_text) for t in THREATS[system]}
    share = round(sum(VALUE[x] for x in threats_map.values()) / len(threats_map), 4)
    worst = worst_domain_risk(threats_map)
    return {
        "system": system,
        "share": share,
        "worst_domain_risk": worst,
        "experimental_preclinical_parser": used_preclinical,
        "threats": threats_map,
        "open": [{"threat": t, "verdict": x, "fix": FIX[t]} for t, x in threats_map.items() if x != "eliminated"],
    }

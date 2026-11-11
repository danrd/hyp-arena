"""Review kind and meta-analysis certainty by code (user decision 2026-11-11, H49 walkthrough stage 5).

(a) The design of a record from PubMed's own publication types where they are decisive, not from the reader's guess:
    Meta-Analysis -> meta_analysis; Systematic Review or Review -> review (kind kept: systematic / narrative); a
    Randomized Controlled Trial the reader called a review or "other" -> rct. Weights are unchanged (a systematic review
    without a pooled estimate still weighs as a review until a check says otherwise).
(c) The certainty of a meta-analysis (GRADE) from its abstract by code; the design weight of a meta-analysis follows it:
    high or moderate 1, low 1/2, very low 1/4, not reported 3/4 (specs/meta-and-nulls-2026-11-09.yaml, variant
    "certainty": R2 0.697 and R3 0.582 against 0.702 and 0.593, inside the 0.03 rule; GRADE is GRADE's own rule).
"""
from __future__ import annotations

import re
from typing import Optional

GRADE_RX = re.compile(r"(high|moderate|low|very[- ]low)[- ](certainty|quality)[^.]{0,40}(evidence|GRADE)|"
                      r"GRADE[^.]{0,80}?\b(high|moderate|low|very[- ]low)\b", re.I)
CERTAINTY_WEIGHT = {"high": 1.0, "moderate": 1.0, "low": 0.5, "very_low": 0.25}
NOT_REPORTED = 0.75


def certainty_from_abstract(text: str) -> str:
    m = GRADE_RX.search(text or "")
    if not m:
        return ""
    w = (m.group(1) or m.group(4) or "").lower().replace(" ", "_").replace("-", "_")
    return w if w in CERTAINTY_WEIGHT else ""


def certainty_factor(certainty: str) -> float:
    return CERTAINTY_WEIGHT.get(certainty or "", NOT_REPORTED)


def design_from_pubtypes(design: str, pubtypes: list[str]) -> tuple[str, str]:
    """(design, review kind: systematic | narrative | '')."""
    pt = {p.lower() for p in pubtypes or []}
    if "meta-analysis" in pt:
        return "meta_analysis", "systematic"
    if "systematic review" in pt:
        return "review", "systematic"
    if "randomized controlled trial" in pt and design in ("review", "other", "unknown"):
        return "rct", ""
    if "review" in pt and design not in ("meta_analysis",):
        return "review", "narrative"
    return design, ""

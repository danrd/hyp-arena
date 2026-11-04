"""Effect class by code from the verbatim effect phrase (user decision 2026-11-04, option A; docs/spec/method-v3.md, section 2).

The extractor decides only whether the finding closest to the claim is a null result ("none") and copies the phrase with the
effect size; the class is computed here, so that "small", "medium" and "large" mean the same thing in every record:

- ratio (odds, risk, hazard ratio; OR, RR, HR, IRR; "8-fold"): >= 2 or <= 0.5 large; >= 1.25 or <= 0.8 medium; otherwise small;
- standardised difference (Cohen's d, Hedges' g, SMD, "effect size"): >= 0.8 large; >= 0.5 medium; otherwise small (absolute value);
- relative change in percent ("+9.3%", "9.3% increase", "reduced by 35%"): > 20 large; >= 5 medium; otherwise small;
- the authors' own word for the size ("small", "modest", "slight" / "moderate" / "large", "substantial", "marked"): that size;
- anything else (raw units such as "+2.4 kg" or "58±11 m", test statistics, p values only): "unclear".

The first kind that matches decides. Thresholds for ratios and d are the usual conventions; those for percent are the user's
working values (2026-11-04) and may change only as a new dated rule.
"""
from __future__ import annotations

import re

CLASSES = ("none", "small", "medium", "large", "unclear")
_NUM = r"(-?\d+(?:\.\d+)?)"
_RATIO = re.compile(r"\b(?:odds ratio|risk ratio|relative risk|hazard ratio|rate ratio|OR|aOR|RR|aRR|HR|aHR|IRR)\b"
                    r"\s*(?:\[[^\]]*\]|\([^)]*\))?\s*(?:=|:|of|was|is)?\s*" + _NUM, re.I)
_FOLD = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*fold\b", re.I)
_SMD = re.compile(r"(?:\bCohen'?s\s+d|\bHedges'?\s+g|\bSMD\b|\beffect size\b|\bd\b|\bg\b)\s*(?:=|:|of|was)?\s*" + _NUM, re.I)
_PCT_WORD = r"(?:increase|increased|decrease|decreased|reduction|reduced|higher|lower|improvement|improved|gain|loss|rise|drop|change)"
_PCT = re.compile(r"([+-−]?\d+(?:\.\d+)?)\s*%\s*" + _PCT_WORD + r"|" + _PCT_WORD + r"\s+(?:of|by)\s+([+-−]?\d+(?:\.\d+)?)\s*%"
                  r"|(?:^|\s|\()([+−-]\d+(?:\.\d+)?)\s*%", re.I)
_WORDS = (("large", r"\b(?:large|substantial|marked|strong)\b"), ("medium", r"\b(?:moderate|medium)\b"),
          ("small", r"\b(?:small|modest|slight|minor)\b"))


def from_phrase(phrase: str) -> str:
    """The class of a verbatim effect phrase, or "unclear" when its kind is not one of the rules."""
    p = (phrase or "").replace("−", "-")
    m = _RATIO.search(p)
    if m:
        x = float(m.group(1))
        if x <= 0:
            return "unclear"
        x = max(x, 1 / x)
        return "large" if x >= 2 else "medium" if x >= 1.25 else "small"
    m = _FOLD.search(p)
    if m:
        x = float(m.group(1))
        return "unclear" if x <= 0 else ("large" if max(x, 1 / x) >= 2 else "medium" if max(x, 1 / x) >= 1.25 else "small")
    m = _SMD.search(p)
    if m:
        x = abs(float(m.group(1)))
        return "large" if x >= 0.8 else "medium" if x >= 0.5 else "small"
    m = _PCT.search(p)
    if m:
        x = abs(float(next(g for g in m.groups() if g)))
        return "large" if x > 20 else "medium" if x >= 5 else "small"
    for cls, pat in _WORDS:
        if re.search(pat, p, re.I):
            return cls
    return "unclear"


def effect_class(phrase: str, extractor_class: str) -> str:
    """"none" when the extractor says the finding closest to the claim is null; otherwise the class of the phrase."""
    if extractor_class == "none":
        return "none"
    return from_phrase(phrase)

"""Effect class by code from the verbatim effect phrase (user decision 2026-11-04, option A; docs/spec/method-v3.md, section 2).

The extractor decides only whether the finding closest to the claim is a null result ("none") and copies the phrase with the
effect size; the class is computed here, so that "small", "medium" and "large" mean the same thing in every record:

- ratio (odds, risk, hazard ratio; OR, RR, HR, IRR; "8-fold"): >= 2 or <= 0.5 large; >= 1.25 or <= 0.8 medium; otherwise small;
- standardised difference (Cohen's d, Hedges' g, SMD, "effect size"): >= 0.8 large; >= 0.5 medium; otherwise small (absolute value);
- relative change in percent ("+9.3%", "9.3% increase", "reduced by 35%", "increased by 12 +/- 3 percent", "by about 40%"): > 20 large;
  >= 5 medium; otherwise small. A bare percent without a sign or a change word ("(20%, p < 0.05)", "65.7% to 42.9%") is not read
  as a change: "unclear";
- the authors' own word for the size ("small", "modest", "slight" / "moderate" / "large", "substantial", "marked"): that size;
- anything else (raw units such as "+2.4 kg" or "58±11 m", test statistics, p values only): "unclear".

The first kind that matches decides. Thresholds for ratios and d are the usual conventions; those for percent are the user's
working values (2026-11-04) and may change only as a new dated rule.
"""
from __future__ import annotations

import re

CLASSES = ("none", "small", "medium", "large", "unclear")
_NUM = r"(-?(?:\d+(?:\.\d+)?|\.\d+))"            # 2026-11-07: also ".67" (no leading zero)
_RATIO = re.compile(r"\b(?:odds ratio|risk ratio|relative risk|hazard ratio|rate ratio|OR|aOR|RR|aRR|HR|aHR|IRR)\b"
                    r"\s*(?:\[[^\]]*\]|\([^)]*\))?\s*,?\s*(?:=|:|of|was|is)?\s*" + _NUM, re.I)      # 2026-11-08: "hazard ratio [HR], 0.82"
_FOLD = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*fold\b", re.I)
_SMD = re.compile(r"(?:\bCohen'?s\s+d|\bHedges'?\s+g|\bSMD\b|\beffect size\b|\bd\b|\bg\b)\s*(?:=|:|of|was)?\s*" + _NUM
                  # 2026-11-07: also the number before the name, "- 1.20 standardised mean difference (SMD)"
                  + r"|(-?\s?\d+(?:\.\d+)?)\s*(?:\(|\[)?\s*(?:standardi[sz]ed mean difference|SMD)\b", re.I)
_PCT_WORD = r"(?:increases?|increased|decreases?|decreased|reduction|reduced|higher|lower|improvements?|improved|gain|loss|rise|drop|change)"
_P = r"\s*(?:(?:±|\+/-|\+-)\s*\d+(?:\.\d+)?\s*)?(?:%|percent\b|per cent\b)"      # "12%", "12 percent", "113 +/- 8 percent"
_PCT = re.compile(r"([+-]?\d+(?:\.\d+)?)" + _P + r"\s*" + _PCT_WORD
                  + r"|" + _PCT_WORD + r"\s+(?:of|by)\s+(?:about\s+|approximately\s+|nearly\s+|~)?([+-]?\d+(?:\.\d+)?)" + _P
                  + r"|\bby\s+(?:about\s+|approximately\s+|nearly\s+|~)?(\d+(?:\.\d+)?)" + _P
                  + r"|(?:^|\s|\()([+-]\d+(?:\.\d+)?)" + _P
                  # 2026-11-08: "Mean Δ% = 40.4%", "ΔEG/CG: 29.67%", "increases from baseline of 21%"
                  + r"|Δ[^0-9]{0,12}?(\d+(?:\.\d+)?)" + _P
                  + r"|" + _PCT_WORD + r"\s+from baseline\s+of\s+(\d+(?:\.\d+)?)" + _P, re.I)
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
        x = abs(float(next(g for g in m.groups() if g).replace(" ", "")))
        return "large" if x >= 0.8 else "medium" if x >= 0.5 else "small"
    m = _PCT.search(p)
    if m:
        x = abs(float(next(g for g in m.groups() if g)))
        return "large" if x > 20 else "medium" if x >= 5 else "small"
    for cls, pat in _WORDS:
        if re.search(pat, p, re.I):
            return cls
    return "unclear"


_DIFF_CI = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*(?:[a-zA-Z%/²]+\s*)?(?:\(|;|,|\[)\s*(?:95\s*%\s*(?:confidence interval|CI)[^0-9-]{0,20})"
                      r"\[?\s*(-?\d+(?:\.\d+)?)\s*(?:to|,|;|–|-)\s*(-?\d+(?:\.\d+)?)", re.I)


def d_from_ci(phrase: str, n: int | None, comparison: str) -> float | None:
    """2026-11-08: a standardised difference from a raw difference with its 95% CI and the sample size: SE = (hi - lo) / 3.92;
    between two groups of n/2, SD = SE * sqrt(n) / 2; before-after in n people, SD = SE * sqrt(n); d = |difference| / SD.
    None when the phrase has no "difference (95% CI lo to hi)" or n is unknown."""
    if not n or n < 4:
        return None
    m = _DIFF_CI.search((phrase or "").replace("−", "-"))
    if not m:
        return None
    diff, lo, hi = (float(m.group(k)) for k in (1, 2, 3))
    se = abs(hi - lo) / 3.92
    if se <= 0:
        return None
    sd = se * (n ** 0.5) / (2 if comparison == "between_groups" else 1)
    return abs(diff) / sd


def effect_class(phrase: str, extractor_class: str) -> str:
    """"none" when the extractor says the finding closest to the claim is null; otherwise the class of the phrase."""
    if extractor_class == "none":
        return "none"
    return from_phrase(phrase)

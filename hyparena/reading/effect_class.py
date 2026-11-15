"""Effect class by code from the verbatim effect phrase (user decision 2026-11-04, option A; archive/docs/spec/method-v3.md, section 2).

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


# Parser extensions (specs/scoring/effect-phrase-2026-11-15.yaml). "interval" is part of the method since 2026-11-15 (more
# written forms of the accepted rule "a raw difference with its 95% interval and n"); the others were scored as variants and
# are off: a switch enters EXTRA only through the manual.
EXTRA: frozenset = frozenset({"interval"})          # of "interval", "means", "two_values", "p_value"

_N = r"([+-]?\d+(?:\.\d+)?)"
_CI_WIDE = re.compile(_N + r"(?:\s*[a-zA-Z%/²°.-]+){0,8}\s*(?:\(|;|,|\[)?\s*(?:95\s*%\s*)?(?:confidence interval|C\.?I\.?)\b\.?"
                      r"[^0-9+-]{0,20}" + _N + r"\s*(?:to|,|;|–|-)\s*" + _N, re.I)
_CI_BRACE = re.compile(_N + r"\s*[a-zA-Z%/²°]*\s*\{\s*" + _N + r"\s*;\s*" + _N + r"\s*\}")
_SMD_WIDE = re.compile(r"\bSMD\b[^0-9+-]{0,20}" + _N, re.I)
_MEAN_SD = re.compile(_N + r"\s*(?:±|\+/-|\+-)\s*(\d+(?:\.\d+)?)")
_FROM_TO = re.compile(r"\bfrom\s+" + _N + r"\s*[a-zA-Zµ%/]*\s+to\s+" + _N, re.I)
_VERSUS = re.compile(r"(?<![/±\d.])" + _N + r"\s*(%?)\s*[a-zA-Zµ/]*\s*(?:vs\.?|versus|compared (?:with|to))\s+" + _N + r"\s*(%?)", re.I)
_P_VALUE = re.compile(r"\bp\s*(=|<|≤)\s*(0?\.\d+)", re.I)


def _d_interval(diff: float, lo: float, hi: float, n: int, comparison: str) -> float | None:
    se = abs(hi - lo) / 3.92
    return abs(diff) / (se * (n ** 0.5) / (2 if comparison == "between_groups" else 1)) if se > 0 else None


def d_extra(phrase: str, n: int | None, comparison: str) -> float | None:
    """A standardised difference from the switched-on extensions "interval" and "means", or None."""
    p = (phrase or "").replace("−", "-")
    if "interval" in EXTRA:
        m = _SMD_WIDE.search(p)
        if m:
            return abs(float(m.group(1)))
        m = _CI_WIDE.search(p) or _CI_BRACE.search(p)
        if m and n and n >= 4:
            diff, lo, hi = (float(m.group(k)) for k in (1, 2, 3))
            if min(lo, hi) <= diff <= max(lo, hi):                 # the number before the interval is its own estimate
                return _d_interval(diff, lo, hi, n, comparison)
    if "means" in EXTRA:
        ms = _MEAN_SD.findall(p)
        if len(ms) == 2:
            (m1, s1), (m2, s2) = ((float(a), float(b)) for a, b in ms)
            sd = ((s1 ** 2 + s2 ** 2) / 2) ** 0.5
            return abs(m1 - m2) / sd if sd > 0 else None
    return None


def class_two_values(phrase: str) -> str:
    """"two_values": the class of "from X to Y" (relative change, percent thresholds) or "X vs Y" (ratio thresholds)."""
    if "two_values" not in EXTRA:
        return "unclear"
    p = (phrase or "").replace("−", "-")
    m = _FROM_TO.search(p)
    if m:
        x, y = float(m.group(1)), float(m.group(2))
        if x == 0:
            return "unclear"
        c = abs(y - x) / abs(x) * 100
        return "large" if c > 20 else "medium" if c >= 5 else "small"
    m = _VERSUS.search(p)
    if m:
        x, y = float(m.group(1)), float(m.group(3))
        if x * y <= 0:
            return "unclear"
        r = max(abs(x), abs(y)) / min(abs(x), abs(y))
        return "large" if r >= 2 else "medium" if r >= 1.25 else "small"
    return "unclear"


def d_from_p(phrase: str, n: int | None, comparison: str) -> float | None:
    """"p_value": d from a two-sided p and n (z from p; 2 z / sqrt(n) between groups, z / sqrt(n) within); "p < x" is a lower bound."""
    if "p_value" not in EXTRA or not n or n < 4:
        return None
    m = _P_VALUE.search(phrase or "")
    if not m or not 0 < float(m.group(2)) < 1:
        return None
    from statistics import NormalDist
    z = NormalDist().inv_cdf(1 - float(m.group(2)) / 2)
    return (2 if comparison == "between_groups" else 1) * z / n ** 0.5


NUMBER_KEYS = ("intervention", "control", "before", "after", "sd_intervention", "sd_control", "sd_before", "sd_after",
               "difference", "ci_low", "ci_high", "p", "ratio", "smd")


def _f(x) -> float | None:
    try:
        return float(str(x).replace("−", "-").replace("–", "-").replace(",", ".").lstrip("<>=≤≥ ").rstrip("% "))
    except ValueError:
        return None


def clean_numbers(numbers, source: str) -> dict[str, str]:
    """The effect numbers of a reader's record (verify_claim/v18) that are written in the abstract: a value whose digits do
    not occur in the source is dropped; "unit" and "ratio_kind" are kept as words."""
    if not isinstance(numbers, dict):
        return {}
    src = source.replace("−", "-").replace("–", "-").replace("·", ".")
    out = {}
    for k in NUMBER_KEYS:
        v = str(numbers.get(k) if numbers.get(k) is not None else "").strip()
        digits = v.lstrip("+-<>=≤≥ ").rstrip("% ")
        if digits and _f(v) is not None and re.search(r"(?<![\d.])" + re.escape(digits) + r"(?![\d])", src):
            out[k] = v
    for k in ("unit", "ratio_kind"):
        if isinstance(numbers.get(k), str) and numbers[k].strip() and out:
            out[k] = numbers[k].strip()[:40]
    return out


def d_from_numbers(numbers: dict, n: int | None, comparison: str) -> tuple[float | None, str]:
    """(d, kind) from the checked effect numbers, the first that applies: "smd" (a standardised difference as stated);
    "ratio" (ln(ratio) * sqrt(3) / pi); "interval" (a difference with its 95% interval and n, as d_from_ci); "means" (two
    values with their standard deviations: the difference over the pooled SD); "change_sd" (a stated difference over the one
    standard deviation given). The record weight uses the kinds the manual names (rules_v32.EFFECT_D_KINDS)."""
    g = {k: _f(v) for k, v in numbers.items() if k in NUMBER_KEYS}
    g = {k: v for k, v in g.items() if v is not None}
    if "smd" in g:
        return abs(g["smd"]), "smd"
    if g.get("ratio", 0) > 0:
        import math
        return abs(math.log(g["ratio"])) * math.sqrt(3) / math.pi, "ratio"
    pair = next(((a, b) for a, b in (("intervention", "control"), ("after", "before")) if a in g and b in g), None)
    diff = g.get("difference", (g[pair[0]] - g[pair[1]]) if pair else None)
    if diff is not None and "ci_low" in g and "ci_high" in g and n and n >= 4 and min(g["ci_low"], g["ci_high"]) <= diff <= max(g["ci_low"], g["ci_high"]):
        d = _d_interval(diff, g["ci_low"], g["ci_high"], n, comparison)
        if d is not None:
            return d, "interval"
    if pair:
        sds = [g.get("sd_" + pair[0]), g.get("sd_" + pair[1])]
        if all(x and x > 0 for x in sds):
            return abs(g[pair[0]] - g[pair[1]]) / ((sds[0] ** 2 + sds[1] ** 2) / 2) ** 0.5, "means"
    sd = next((g[k] for k in ("sd_control", "sd_before", "sd_intervention", "sd_after") if g.get(k, 0) > 0), None)
    if diff is not None and sd:
        return abs(diff) / sd, "change_sd"
    return None, ""


def effect_class(phrase: str, extractor_class: str) -> str:
    """"none" when the extractor says the finding closest to the claim is null; otherwise the class of the phrase."""
    if extractor_class == "none":
        return "none"
    return from_phrase(phrase)

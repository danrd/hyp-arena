"""Name-swap diagnostic harness (no model calls).

Intended for components where a language model reads the text (normalizer, verifier, baseline judges); not for the rule layer of the ranking, which must be invariant to a consistent renaming (name and identifier together).
"""
import re
from dataclasses import dataclass
from typing import Callable, Any, Sequence

import numpy as np
import scipy.stats as stats


@dataclass
class SwapVariants:
    own: str
    neutral: str
    famous: str
    count_neutral: int
    count_famous: int


@dataclass
class PriorBias:
    mean_neutral_minus_own: float
    mean_famous_minus_own: float
    ci_neutral: tuple[float, float]
    ci_famous: tuple[float, float]
    n_items: int
    per_item: list[dict[str, Any]]


def _replace_word(text: str, word: str, replacement: str, preserve_case: bool = False) -> tuple[str, int]:
    # Use word boundaries for replacement to ensure we don't match substrings inside other words
    pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)

    if not preserve_case:
        res, count = pattern.subn(replacement, text)
        return res, count

    def match_replacer(match: re.Match) -> str:
        matched_str = match.group(0)
        if matched_str.isupper():
            return replacement.upper()
        elif matched_str.istitle():
            return replacement.title()
        elif matched_str.islower():
            return replacement.lower()
        else:
            return replacement

    res, count = pattern.subn(match_replacer, text)
    return res, count


def swap_variants(text: str, name: str, aliases: Sequence[str] = (), neutral: str = "Compound_42", famous: str = "rapamycin") -> SwapVariants:
    """Create neutral and famous variants of a text by replacing a name and its aliases."""
    neutral_text = text
    famous_text = text
    count_neutral = 0
    count_famous = 0

    words_to_replace = [name] + list(aliases)

    # It's important to sort by length descending to avoid partial matches
    words_to_replace.sort(key=len, reverse=True)

    for word in words_to_replace:
        neutral_text, c_n = _replace_word(neutral_text, word, neutral, preserve_case=False)
        famous_text, c_f = _replace_word(famous_text, word, famous, preserve_case=True)
        count_neutral += c_n
        count_famous += c_f

    return SwapVariants(
        own=text,
        neutral=neutral_text,
        famous=famous_text,
        count_neutral=count_neutral,
        count_famous=count_famous
    )


def _bootstrap_ci(data: np.ndarray, n_resamples: int = 1000, alpha: float = 0.05, seed: int | np.random.Generator | None = 42) -> tuple[float, float]:
    """Compute percentile bootstrap confidence interval for the mean."""
    n = len(data)
    if n == 0:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, n, size=(n_resamples, n))
    means = np.mean(data[indices], axis=1)
    return float(np.percentile(means, 100 * (alpha / 2))), float(np.percentile(means, 100 * (1 - alpha / 2)))


def prior_bias_score(component: Callable[[str], float], items: Sequence[tuple[str, str, Sequence[str]]], neutral: str = "Compound_42", famous: str = "rapamycin", n_resamples: int = 1000, seed: int | np.random.Generator | None = 42) -> PriorBias:
    """Score bias under name swapping for a component."""
    neutral_diffs = []
    famous_diffs = []
    per_item = []

    for text, name, aliases in items:
        variants = swap_variants(text, name, aliases, neutral, famous)
        own_score = component(variants.own)
        neutral_score = component(variants.neutral)
        famous_score = component(variants.famous)

        diff_neutral = neutral_score - own_score
        diff_famous = famous_score - own_score

        neutral_diffs.append(diff_neutral)
        famous_diffs.append(diff_famous)
        per_item.append({
            "own": own_score,
            "neutral": neutral_score,
            "famous": famous_score,
            "count_neutral": variants.count_neutral,
            "count_famous": variants.count_famous
        })

    neutral_arr = np.array(neutral_diffs)
    famous_arr = np.array(famous_diffs)

    return PriorBias(
        mean_neutral_minus_own=float(np.mean(neutral_arr)) if len(neutral_arr) > 0 else 0.0,
        mean_famous_minus_own=float(np.mean(famous_arr)) if len(famous_arr) > 0 else 0.0,
        ci_neutral=_bootstrap_ci(neutral_arr, n_resamples=n_resamples, seed=seed) if len(neutral_arr) > 0 else (0.0, 0.0),
        ci_famous=_bootstrap_ci(famous_arr, n_resamples=n_resamples, seed=seed) if len(famous_arr) > 0 else (0.0, 0.0),
        n_items=len(items),
        per_item=per_item
    )


def rank_shift(component: Callable[[str], float], items: Sequence[tuple[str, str, Sequence[str]]], famous: str = "rapamycin", n_resamples: int = 1000, seed: int | np.random.Generator | None = 42) -> tuple[float, tuple[float, float]]:
    """Compute Kendall tau-b between ranking under own and famous texts, with a bootstrap CI."""
    own_scores = []
    famous_scores = []

    for text, name, aliases in items:
        variants = swap_variants(text, name, aliases, neutral="Compound_42", famous=famous)
        own_scores.append(component(variants.own))
        famous_scores.append(component(variants.famous))

    tau, _ = stats.kendalltau(own_scores, famous_scores)
    if np.isnan(tau):
        tau = 0.0

    # Bootstrap CI for tau
    n = len(items)
    if n < 2:
        return float(tau), (float(tau), float(tau))

    rng = np.random.default_rng(seed)
    indices = rng.integers(0, n, size=(n_resamples, n))
    taus = []
    for idx in indices:
        t, _ = stats.kendalltau(np.array(own_scores)[idx], np.array(famous_scores)[idx])
        if np.isnan(t):
            t = 0.0
        taus.append(t)

    ci_low = float(np.percentile(taus, 2.5))
    ci_high = float(np.percentile(taus, 97.5))

    return float(tau), (ci_low, ci_high)

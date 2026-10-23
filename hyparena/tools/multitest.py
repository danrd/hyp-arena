"""Procedures for multiple testing and e-values.

This module implements classical p-value adjustments and e-value procedures to
control false discovery rates and family-wise error rates when evaluating
multiple hypotheses.
"""

from typing import NamedTuple, Union

import numpy as np

class MultiTestResult(NamedTuple):
    reject: np.ndarray
    adjusted_p: np.ndarray

def _validate_p(p: Union[np.ndarray, list]) -> np.ndarray:
    p_arr = np.asarray(p, dtype=float)
    if p_arr.size > 0:
        if np.any(np.isnan(p_arr)) or np.any(p_arr < 0) or np.any(p_arr > 1):
            raise ValueError("p-values must be between 0 and 1 and not NaN")
    return p_arr

def _validate_e(e: Union[np.ndarray, list]) -> np.ndarray:
    e_arr = np.asarray(e, dtype=float)
    if e_arr.size > 0:
        if np.any(np.isnan(e_arr)) or np.any(e_arr < 0):
            raise ValueError("e-values must be non-negative and not NaN")
    return e_arr

def bonferroni(p: Union[np.ndarray, list], alpha: float = 0.05) -> MultiTestResult:
    """Bonferroni correction for family-wise error rate control."""
    p_arr = _validate_p(p)
    if p_arr.size == 0:
        return MultiTestResult(np.array([], dtype=bool), np.array([], dtype=float))
    m = len(p_arr)
    adj_p = np.minimum(1.0, p_arr * m)
    return MultiTestResult(adj_p <= alpha, adj_p)

def holm(p: Union[np.ndarray, list], alpha: float = 0.05) -> MultiTestResult:
    """Holm step-down procedure for family-wise error rate control."""
    p_arr = _validate_p(p)
    if p_arr.size == 0:
        return MultiTestResult(np.array([], dtype=bool), np.array([], dtype=float))
    m = len(p_arr)
    order = np.argsort(p_arr)
    p_ordered = p_arr[order]

    steps = m - np.arange(m)
    adj_p_ordered = np.minimum(1.0, np.maximum.accumulate(p_ordered * steps))

    adj_p = np.empty_like(p_arr)
    adj_p[order] = adj_p_ordered

    return MultiTestResult(adj_p <= alpha, adj_p)

def benjamini_hochberg(p: Union[np.ndarray, list], alpha: float = 0.05) -> MultiTestResult:
    """Benjamini-Hochberg procedure for false discovery rate control."""
    p_arr = _validate_p(p)
    if p_arr.size == 0:
        return MultiTestResult(np.array([], dtype=bool), np.array([], dtype=float))
    m = len(p_arr)
    order = np.argsort(p_arr)
    p_ordered = p_arr[order]

    steps = m / (np.arange(m) + 1)
    adj_p_ordered = np.minimum(1.0, np.minimum.accumulate((p_ordered * steps)[::-1])[::-1])

    adj_p = np.empty_like(p_arr)
    adj_p[order] = adj_p_ordered

    return MultiTestResult(adj_p <= alpha, adj_p)

def benjamini_yekutieli(p: Union[np.ndarray, list], alpha: float = 0.05) -> MultiTestResult:
    """Benjamini-Yekutieli procedure for false discovery rate control under arbitrary dependence."""
    p_arr = _validate_p(p)
    if p_arr.size == 0:
        return MultiTestResult(np.array([], dtype=bool), np.array([], dtype=float))
    m = len(p_arr)
    cm = np.sum(1.0 / (np.arange(m) + 1))

    order = np.argsort(p_arr)
    p_ordered = p_arr[order]

    steps = m * cm / (np.arange(m) + 1)
    adj_p_ordered = np.minimum(1.0, np.minimum.accumulate((p_ordered * steps)[::-1])[::-1])

    adj_p = np.empty_like(p_arr)
    adj_p[order] = adj_p_ordered

    return MultiTestResult(adj_p <= alpha, adj_p)

def p_to_e(p: Union[np.ndarray, list], kappa: float = 0.5) -> np.ndarray:
    """Calibrator e-value from a p-value."""
    p_arr = _validate_p(p)
    if p_arr.size == 0:
        return np.array([], dtype=float)
    if not (0 < kappa < 1):
        raise ValueError("kappa must be in (0, 1)")
    # Using np.where to handle p=0 gracefully if desired, or let it inf.
    # The requirement does not strictly specify p=0 behavior but usually p**(kappa-1) is inf which is a valid e-value.
    with np.errstate(divide='ignore'):
        e = kappa * (p_arr ** (kappa - 1.0))
    return e

def e_bh(e: Union[np.ndarray, list], alpha: float = 0.05) -> np.ndarray:
    """The e-BH procedure (Wang and Ramdas 2022) for e-values."""
    e_arr = _validate_e(e)
    if e_arr.size == 0:
        return np.array([], dtype=bool)
    m = len(e_arr)
    order = np.argsort(e_arr)[::-1]  # Sort decreasing
    e_ordered = e_arr[order]

    k = np.arange(1, m + 1)
    condition = e_ordered >= (m / (alpha * k))

    reject = np.zeros_like(e_arr, dtype=bool)
    if np.any(condition):
        k_star = np.max(np.where(condition)[0]) + 1
        reject[order[:k_star]] = True

    return reject

def combine_e_values(e_list: list[Union[np.ndarray, list]]) -> np.ndarray:
    """Combine e-values by multiplying them over rounds."""
    if not e_list:
        return np.array([], dtype=float)
    valid_e_list = [_validate_e(e) for e in e_list]
    return np.prod(valid_e_list, axis=0)

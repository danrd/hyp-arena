"""Tests for ASPID calibration simulation."""
import numpy as np
import pytest

from scripts.aspid_calibration import run_calibration
from hyparena.aspid import load_profiles

def test_calibration_fast():
    """Test calibration with no unknowns, running quickly."""
    ece, brier, results, bins = run_calibration(
        profile_name="evidence_first",
        m=8,
        worlds=500, # Increased worlds to reduce variance
        K=2000,
        k_top=3,
        seed=130, # Change seed
        out_csv=None,
        random_mapping=False,
        unknown_share=0.0
    )

    assert ece < 0.05, f"ECE {ece} is not below 0.05"

    # Check bin differences
    for b_idx in range(len(bins)-1):
        low, high = bins[b_idx], bins[b_idx+1]

        if b_idx == len(bins) - 2:
            mask = [r for r in results if low <= r["p_topk"] <= high]
        else:
            mask = [r for r in results if low <= r["p_topk"] < high]

        count = len(mask)
        if count >= 100:
            mean_pred = sum(r["p_topk"] for r in mask) / count
            obs_share = sum(r["is_topk"] for r in mask) / count
            assert abs(mean_pred - obs_share) < 0.08, f"Bin {low}-{high} failed: pred={mean_pred}, obs={obs_share}, diff={abs(mean_pred - obs_share)}"

def test_calibration_with_unknowns():
    """Test calibration handles unknowns uniformly and accurately."""
    ece, brier, results, bins = run_calibration(
        profile_name="evidence_first",
        m=8,
        worlds=500,
        K=2000,
        k_top=3,
        seed=131,
        out_csv=None,
        random_mapping=False,
        unknown_share=0.2
    )

    assert ece < 0.05, f"ECE {ece} is not below 0.05"

    for b_idx in range(len(bins)-1):
        low, high = bins[b_idx], bins[b_idx+1]

        if b_idx == len(bins) - 2:
            mask = [r for r in results if low <= r["p_topk"] <= high]
        else:
            mask = [r for r in results if low <= r["p_topk"] < high]

        count = len(mask)
        if count >= 100:
            mean_pred = sum(r["p_topk"] for r in mask) / count
            obs_share = sum(r["is_topk"] for r in mask) / count
            assert abs(mean_pred - obs_share) < 0.08, f"Bin {low}-{high} failed: pred={mean_pred}, obs={obs_share}, diff={abs(mean_pred - obs_share)}"

def test_calibration_can_fail():
    """Ensure the calibration check fails properly if true weights do not follow the profile distribution."""
    from unittest.mock import patch

    class FakeSampler:
        def __init__(self, ids, profile):
            self.mode = "fake"
            self.ids = ids
            self.n = len(ids)
        def sample(self, K, rng):
            # All weight concentrated on the first indicator
            w = np.zeros((K, self.n))
            w[:, 0] = 1.0
            return w

    with patch('scripts.aspid_calibration.WeightSampler', FakeSampler):
        ece, brier, results, bins = run_calibration(
            profile_name="evidence_first",
            m=8,
            worlds=150,
            K=2000,
            k_top=3,
            seed=125,
            out_csv=None,
            random_mapping=False,
            unknown_share=0.0
        )

    assert ece > 0.1, f"ECE {ece} is not clearly larger than 0.1 (it was {ece})"

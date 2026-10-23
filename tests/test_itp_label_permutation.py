import json
from pathlib import Path

import numpy as np

from scripts.itp_label_permutation import permutation_test


import scipy.stats


def test_random_labels_false_positive_rate():
    # Test (b): on random labels over many seeds, the rejection rate at alpha=0.05
    # is within a binomial interval of 0.05
    n_runs = 200
    n_perm = 200 # Keep n small enough to be fast
    alpha = 0.05

    # Base expected scores (say 20 items)
    expected = np.linspace(1.0, 0.0, 20)

    rejections = 0
    rng = np.random.default_rng(42)

    for i in range(n_runs):
        labels = rng.permutation(np.concatenate([np.ones(10), np.zeros(10)]))
        res = permutation_test(labels, expected, tol=0.002, std=None, K=None, n_perm=n_perm, seed=i)
        if res["p_value"] <= alpha:
            rejections += 1

    fp_rate = rejections / n_runs

    # 99% binomial confidence interval for p=0.05, n=200
    # Expected variance = np(1-p)
    # 200 * 0.05 = 10 expected rejections
    lo, hi = scipy.stats.binom.interval(0.99, n_runs, alpha)

    assert lo <= rejections <= hi, f"FP rate {fp_rate} (rejections={rejections}) outside expected binomial interval [{lo}, {hi}]"


def test_all_equal_scores():
    # Test (c): tie handling: all-equal scores give AUC 0.5 and the permutation null is concentrated at 0.5
    expected = np.zeros(20)
    labels = np.concatenate([np.ones(10), np.zeros(10)])

    n_perm = 200
    res = permutation_test(labels, expected, tol=0.002, std=None, K=None, n_perm=n_perm, seed=42)

    assert res["observed_auc"] == 0.5
    assert np.isclose(res["null_mean"], 0.5)
    assert np.isclose(res["null_2.5"], 0.5)
    assert np.isclose(res["null_97.5"], 0.5)


def test_script_on_snapshot(tmp_path):
    # Test (d): the script runs on the committed snapshot and returns an AUC between 0.4 and 0.9
    # and the number of ranked rows equal to the number of rows with outcome ranked.
    import subprocess
    import csv
    import sys

    snapshot_path = "tests/fixtures/itp2010_snapshot.csv"

    # Count expected ranked rows
    with open(snapshot_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        ranked_count = sum(1 for row in reader if row.get("outcome") == "ranked")

    out_path = tmp_path / "test_perm_out.json"

    res = subprocess.run(
        [sys.executable, "-m", "scripts.itp_label_permutation", snapshot_path, "--n", "100", "--out", str(out_path)],
        capture_output=True, text=True, check=True, cwd=Path(__file__).resolve().parents[1]
    )

    assert out_path.exists()

    with open(out_path) as f:
        data = json.load(f)

    assert 0.4 <= data["observed_tied_auc"] <= 0.9

    # Check that lengths match what was loaded
    from scripts.itp_label_permutation import load_data
    labels, expected, std, K = load_data(snapshot_path)
    assert len(labels) == ranked_count


def test_perfect_ordering():
    # Synthetic data with perfect ordering
    # Using 30 items to make sure random permutations never perfectly align.
    expected = np.linspace(1.0, 0.0, 30)
    labels = np.concatenate([np.ones(15), np.zeros(15)])

    n_perm = 1000
    res = permutation_test(labels, expected, tol=0.002, std=None, K=None, n_perm=n_perm, seed=42)

    assert res["observed_auc"] == 1.0
    # Minimum possible p-value (since none of the 1000 random permutations will match 1.0)
    assert res["p_value"] == 1.0 / (n_perm + 1)

"""Aggregation of per-criterion ratings without explicit weights. Based on the method of randomized
aggregated indicators (МРСП, part of Hovanov's АСПИД methodology; international analogue: SMAA) and adapted
to pairwise ratings; see docs/architecture.md, 3a, for what is ours.

Only an order of importance of the criteria is given, e.g. value >= evidence_support >= testability >=
novelty (groups of equally important criteria allowed). The weight vector is treated as random and uniform
over all weight vectors consistent with that order.

Indicator per criterion: the expected share of wins against the other hypotheses of the same pool, under
the rating system's own win probability (Bradley-Terry and Elo: logistic; TrueSkill: its Gaussian formula).
It is computed in every Monte Carlo sample from ratings drawn within their uncertainty (Bradley-Terry: its
standard error; TrueSkill: sigma; Elo, which has none: a bootstrap of the match log), so the spread carries
the uncertainty of the tournament as well as of the weights. The share depends on the pool and the judges:
it compares hypotheses within one run, not across runs. Systems are compared by external labels, never by
these numbers (docs/comparison.md).

Output per hypothesis: expected aggregated score, its spread, a rank interval and per-criterion win shares
with intervals; for the top: the probability that one hypothesis outranks another. When no order is given,
the criteria's explicit weights are used and only the ratings are sampled."""
from __future__ import annotations

import math

import numpy as np

from hyparena.rating import elo_ratings
from hyparena.state import Match, Rating

#: TrueSkill defaults (Herbrich et al. 2006); beta sets its win probability.
TS_MU, TS_SIGMA = 25.0, 25.0 / 3
TS_BETA = TS_SIGMA / 2
#: Pools larger than this play against a random subset of opponents in each sample (cost N x opponents).
MAX_OPPONENTS = 200


def groups_of(importance: list) -> list[list[str]]:
    """Normalize an importance order: each item is a criterion name or a list of equally important names."""
    return [[g] if isinstance(g, str) else list(g) for g in importance]


def centroid_weights(groups: list[list[str]]) -> dict[str, float]:
    """Expected weights under the uniform distribution on the ordered region: position k of n gets
    (1/n) * sum_{j>=k} 1/j; members of a group share the mean of their positions."""
    n = sum(len(g) for g in groups)
    pos = [sum(1.0 / j for j in range(k, n + 1)) / n for k in range(1, n + 1)]
    out, k = {}, 0
    for g in groups:
        share = sum(pos[k:k + len(g)]) / len(g)
        out.update({c: share for c in g})
        k += len(g)
    return out


def sample_weights(groups: list[list[str]], names: list[str], n: int, rng: np.random.Generator) -> np.ndarray:
    """(n, len(names)) weights, uniform over the region where every criterion of an earlier group weighs
    at least as much as every criterion of a later group: a flat Dirichlet sample sorted in decreasing
    order, its largest values assigned to the first group in random order, and so on (exact by symmetry)."""
    size = sum(len(g) for g in groups)
    w = -np.sort(-rng.dirichlet(np.ones(size), size=n), axis=1)
    out = np.zeros((n, len(names)))
    col = {c: i for i, c in enumerate(names)}
    k = 0
    for g in groups:
        block = w[:, k:k + len(g)]
        if len(g) > 1:
            block = rng.permuted(block, axis=1)
        for j, c in enumerate(g):
            out[:, col[c]] = block[:, j]
        k += len(g)
    return out


def _draws(ratings: dict[str, Rating], ids: list[str], kind: str, n: int, rng: np.random.Generator,
           matches: list[Match] | None, axis: str) -> np.ndarray:
    """(n, len(ids)) ratings drawn within their uncertainty, on the scale where `_win` applies."""
    if kind == "elo":
        base = np.array([ratings[h].score for h in ids])
        if not matches:
            return np.tile(base, (n, 1)) * math.log(10) / 400
        boots = min(n, 200)                      # resample the log, keep its order (Elo is sequential)
        out = np.empty((boots, len(ids)))
        for b in range(boots):
            pick = np.sort(rng.integers(0, len(matches), len(matches)))
            r = elo_ratings(ids, [matches[i] for i in pick], axis)
            out[b] = [r[h].score for h in ids]
        return out[np.arange(n) % boots] * math.log(10) / 400
    mu = np.array([ratings[h].score for h in ids])
    se = np.array([ratings[h].se for h in ids])
    return mu + se * rng.standard_normal((n, len(ids)))


def _ndtr(x: np.ndarray) -> np.ndarray:
    """Standard normal CDF via erf (Abramowitz-Stegun 7.1.26, error below 1.5e-7)."""
    z = np.abs(x) / math.sqrt(2)
    t = 1.0 / (1.0 + 0.3275911 * z)
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
    erf = 1.0 - poly * np.exp(-z * z)
    return 0.5 * (1.0 + np.sign(x) * erf)


def _win(diff: np.ndarray, kind: str) -> np.ndarray:
    """Probability of winning given the rating difference, in the rating system's own model."""
    if kind == "trueskill":
        return _ndtr(diff / (math.sqrt(2) * TS_BETA))
    return 1.0 / (1.0 + np.exp(-diff))


def win_share(theta: np.ndarray, kind: str, rng: np.random.Generator) -> np.ndarray:
    """(n, N) expected share of wins of each hypothesis against the others of the pool, per sample."""
    n, N = theta.shape
    if N < 2:
        return np.full((n, N), 0.5)
    if N - 1 <= MAX_OPPONENTS:
        p = _win(theta[:, :, None] - theta[:, None, :], kind)          # (n, N, N)
        idx = np.arange(N)
        p[:, idx, idx] = 0.0
        return p.sum(2) / (N - 1)
    out = np.empty((n, N))
    step = max(1, int(2e6 // (N * MAX_OPPONENTS)))                     # samples per chunk, bounded memory
    for s in range(0, n, step):
        th = theta[s:s + step]
        opp = np.take_along_axis(th, rng.integers(0, N, (len(th), MAX_OPPONENTS)), 1)   # random opponents
        out[s:s + step] = _win(th[:, :, None] - opp[:, None, :], kind).mean(2)
    return out


def mrsp(ratings: dict[str, dict[str, Rating]], names: list[str], ids: list[str], kind: str = "bt",
         importance: list | None = None, weights: dict[str, float] | None = None, n: int = 2000,
         seed: int = 0, top: int = 10, matches: list[Match] | None = None) -> dict:
    """Randomized aggregation over `ids`. Returns {"by_id": {id: {mean, sd, rank_lo, rank_hi, p_top,
    criteria: {c: {share, lo, hi}}}}, "order": ids by expected score, "dominance": {a: {b: P(a above b)}}
    for the first `top` ids}. `matches` is needed for the Elo bootstrap."""
    if not ids or not names:
        return {"by_id": {}, "order": [], "dominance": {}}
    rng = np.random.default_rng(seed)
    N = len(ids)
    if N > MAX_OPPONENTS:                         # keep the cost about n * N * MAX_OPPONENTS per criterion
        n = max(200, min(n, int(1e7 / (N * MAX_OPPONENTS))))
    if importance:
        w = sample_weights(groups_of(importance), names, n, rng)
    else:
        fixed = np.array([(weights or {}).get(c, 1.0) for c in names])
        w = np.tile(fixed / fixed.sum(), (n, 1))
    total = np.zeros((n, N))
    per = {}
    for j, c in enumerate(names):
        share = win_share(_draws(ratings[c], ids, kind, n, rng, matches, c), kind, rng)
        per[c] = (share.mean(0), np.percentile(share, 5, axis=0), np.percentile(share, 95, axis=0))
        total += w[:, [j]] * share
    ranks = (-total).argsort(axis=1).argsort(axis=1) + 1          # 1 = best, per sample
    mean, sd = total.mean(0), total.std(0)
    k = max(1, min(top, N))
    by_id = {h: {"mean": float(mean[i]), "sd": float(sd[i]),
                 "rank_lo": int(np.percentile(ranks[:, i], 5)), "rank_hi": int(np.percentile(ranks[:, i], 95)),
                 "p_top": float((ranks[:, i] <= k).mean()),
                 "criteria": {c: {"share": float(m[i]), "lo": float(lo[i]), "hi": float(hi[i])}
                              for c, (m, lo, hi) in per.items()}} for i, h in enumerate(ids)}
    order = [ids[i] for i in np.argsort(-mean)]
    head = [ids.index(h) for h in order[:k]]
    dominance = {ids[a]: {ids[b]: float((total[:, a] > total[:, b]).mean()) for b in head if b != a} for a in head}
    return {"by_id": by_id, "order": order, "dominance": dominance, "samples": n,
            "importance": importance or None, "top": k, "indicator": "win share against the pool"}

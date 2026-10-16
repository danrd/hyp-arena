"""Aggregation of per-criterion ratings without explicit weights. Based on the method of randomized
aggregated indicators (МРСП, part of Hovanov's АСПИД methodology; international analogue: SMAA) and adapted
to pairwise ratings; see docs/architecture.md, 3a, for what is ours.

Only an order of importance of the criteria is given, e.g. value >= evidence_support >= testability >=
novelty (groups of equally important criteria allowed). The weight vector is treated as random and uniform
over all weight vectors consistent with that order. Each criterion's rating is mapped to [0, 1] as the
probability of beating an average hypothesis on that criterion, and is also sampled within its standard
error, so the result carries both kinds of uncertainty. Output per hypothesis: expected aggregated score,
its spread and a rank interval; for the top: the probability that one hypothesis outranks another.

The expected weights under this distribution are the rank-order centroid weights, so the expected score
is close to a weighted sum with those weights; the added value is the spread and the dominance
probabilities. When no order is given, the criteria's explicit weights are used and only the ratings are
sampled."""
from __future__ import annotations

import math

import numpy as np

from hyparena.state import Rating

#: TrueSkill defaults (Herbrich et al. 2006), used to put its ratings on the logit scale.
TS_MU, TS_SIGMA = 25.0, 25.0 / 3
TS_BETA = TS_SIGMA / 2


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


def to_logit(rating: Rating, kind: str) -> tuple[float, float]:
    """A rating and its standard error as log-odds of beating an average hypothesis."""
    if kind == "elo":                                   # 400 Elo points = a factor of 10 in odds
        return (rating.score - 1200.0) * math.log(10) / 400.0, 0.0
    if kind == "trueskill":                             # Phi(d / (sqrt(2) beta)) ~ logistic(1.702 * ...)
        f = 1.702 / (math.sqrt(2) * TS_BETA)
        return (rating.score - TS_MU) * f, rating.se * f
    return rating.score, rating.se                      # Bradley-Terry log-strength


def mrsp(ratings: dict[str, dict[str, Rating]], names: list[str], ids: list[str], kind: str = "bt",
         importance: list | None = None, weights: dict[str, float] | None = None,
         n: int = 2000, seed: int = 0, top: int = 10) -> dict:
    """Randomized aggregation over `ids`. Returns {"by_id": {id: {mean, sd, rank_lo, rank_hi, p_top}},
    "order": ids by expected score, "dominance": {a: {b: P(a outranks b)}} for the first `top` ids}."""
    if not ids or not names:
        return {"by_id": {}, "order": [], "dominance": {}}
    rng = np.random.default_rng(seed)
    if importance:
        w = sample_weights(groups_of(importance), names, n, rng)
    else:
        fixed = np.array([(weights or {}).get(c, 1.0) for c in names])
        w = np.tile(fixed / fixed.sum(), (n, 1))
    total = np.zeros((n, len(ids)))
    for j, c in enumerate(names):
        mean_se = [to_logit(ratings[c][h], kind) for h in ids]
        mu = np.array([m for m, _ in mean_se])
        se = np.array([s for _, s in mean_se])
        theta = mu + se * rng.standard_normal((n, len(ids)))
        total += w[:, [j]] * (1.0 / (1.0 + np.exp(-theta)))
    ranks = (-total).argsort(axis=1).argsort(axis=1) + 1          # 1 = best, per sample
    mean, sd = total.mean(0), total.std(0)
    k = max(1, min(top, len(ids)))
    by_id = {h: {"mean": float(mean[i]), "sd": float(sd[i]),
                 "rank_lo": int(np.percentile(ranks[:, i], 5)), "rank_hi": int(np.percentile(ranks[:, i], 95)),
                 "p_top": float((ranks[:, i] <= k).mean())} for i, h in enumerate(ids)}
    order = [ids[i] for i in np.argsort(-mean)]
    head = [ids.index(h) for h in order[:k]]
    dominance = {ids[a]: {ids[b]: float((total[:, a] > total[:, b]).mean()) for b in head if b != a} for a in head}
    return {"by_id": by_id, "order": order, "dominance": dominance, "samples": n,
            "importance": importance or None, "top": k}

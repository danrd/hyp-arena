"""Bradley-Terry ratings per axis and adaptive pair selection (ported from sim.py).

Uses dense N x N count matrices, which is fine up to a few thousand active hypotheses."""
from __future__ import annotations

import random

import numpy as np

from hyparena.state import Match, Rating


def fit_bt(ids: list[str], matches: list[Match], axis: str, iters: int = 100) -> dict[str, Rating]:
    """Fit log-strengths and Fisher-information standard errors from decided matches on one criterion."""
    n = len(ids)
    if n == 0:
        return {}
    index = {h: i for i, h in enumerate(ids)}
    wins = np.zeros((n, n))
    for m in matches:
        winner = m.winners.get(axis)
        if winner is None or m.a not in index or m.b not in index:
            continue
        loser = m.b if winner == m.a else m.a
        wins[index[winner], index[loser]] += 1
    games = wins + wins.T
    total = wins.sum(1) + 0.5          # one virtual draw against a unit-strength item keeps the fit finite
    p = np.ones(n)
    for _ in range(iters):
        denom = (games / (p[:, None] + p[None, :])).sum(1) + 1.0 / (p + 1.0)
        p = total / denom
        p /= np.exp(np.log(p).mean())
    q = p[:, None] * p[None, :] / (p[:, None] + p[None, :]) ** 2
    info = (games * q).sum(1) + p / (p + 1.0) ** 2
    se = 1.0 / np.sqrt(info)
    played = games.sum(1)
    return {h: Rating(score=float(np.log(p[i])), se=float(se[i]), games=int(played[i]))
            for h, i in index.items()}


def combined(ratings: dict[str, dict[str, Rating]], weights: dict[str, float],
             ids: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Weighted score and its standard error per id, over the criteria in `weights`."""
    score = np.array([sum(w * ratings[c][h].score for c, w in weights.items()) for h in ids])
    se = np.sqrt(np.array([sum((w * ratings[c][h].se) ** 2 for c, w in weights.items()) for h in ids]))
    return score, se


def _neighbour_pairs(order: list[str], rng: random.Random, limit: int) -> list[tuple[str, str]]:
    if len(order) > 2 and rng.random() < 0.5:     # shift the pairing, but never drop the only pair
        order = order[1:]
    pairs = [(order[i], order[i + 1]) for i in range(0, len(order) - 1, 2)]
    if len(pairs) > limit:
        pairs = rng.sample(pairs, limit)
    return pairs


def select_pairs(ids: list[str], ratings: dict[str, dict[str, Rating]], weights: dict[str, float],
                 rng: random.Random, n_matches: int, top_k: int, swiss_share: float = 0.2,
                 z: float = 2.0) -> list[tuple[str, str]]:
    """Elimination towards the top-k plus a Swiss exploration share (cluster bias not implemented)."""
    n = len(ids)
    if n < 2:
        return []
    score, se = combined(ratings, weights, ids)
    jitter = [rng.gauss(0, 0.05) for _ in range(n)]
    by_score = sorted(range(n), key=lambda i: -(score[i] + jitter[i]))

    n_explore = int(n_matches * swiss_share)
    explore = _neighbour_pairs([ids[i] for i in by_score], rng, n_explore) if n_explore else []

    k = max(1, min(top_k, n))
    kth_lower = np.sort(score - z * se)[-k]
    cand = [i for i in range(n) if score[i] + z * se[i] >= kth_lower]
    if len(cand) < 4:
        cand = by_score[: max(4, 2 * k)]
    cand_order = sorted(cand, key=lambda i: -(score[i] + jitter[i]))
    focus = _neighbour_pairs([ids[i] for i in cand_order], rng, max(0, n_matches - len(explore)))

    seen, out = set(), []
    for a, b in focus + explore:
        key = frozenset((a, b))
        if key not in seen:
            seen.add(key)
            out.append((a, b))
    return out


# ---- Co-Scientist baseline: online Elo and its pairing priorities ----

def elo_ratings(ids: list[str], matches: list[Match], axis: str, k: float = 32.0,
                init: float = 1200.0) -> dict[str, Rating]:
    """Sequential Elo over the match log in order (Co-Scientist starts every hypothesis at 1200; its K
    factor is not given in the paper, 32 is the chess default). No standard error: se is 0."""
    elo, games = {h: init for h in ids}, {h: 0 for h in ids}
    for m in matches:
        w = m.winners.get(axis)
        if w is None or m.a not in elo or m.b not in elo:
            continue
        expected_a = 1.0 / (1.0 + 10 ** ((elo[m.b] - elo[m.a]) / 400.0))
        score_a = 1.0 if w == m.a else 0.0
        elo[m.a] += k * (score_a - expected_a)
        elo[m.b] -= k * (score_a - expected_a)
        games[m.a] += 1
        games[m.b] += 1
    return {h: Rating(score=elo[h], se=0.0, games=games[h]) for h in ids}


def select_pairs_coscientist(ids: list[str], ratings: dict[str, dict[str, Rating]], weights: dict[str, float],
                             clusters: dict[str, int | None], rng: random.Random, n_matches: int,
                             top_frac: float = 0.25, new_games: int = 2) -> list[tuple[str, str]]:
    """Co-Scientist's priorities: newer and top-ranked hypotheses play first, preferably against similar
    ones (same proximity cluster), otherwise against the nearest in rating."""
    if len(ids) < 2:
        return []
    score, _ = combined(ratings, weights, ids)
    by = dict(zip(ids, score))
    first = next(iter(weights))
    games = {h: ratings[first][h].games for h in ids}
    top = sorted(ids, key=lambda h: -by[h])[: max(2, int(len(ids) * top_frac))]
    priority = list(dict.fromkeys([h for h in ids if games[h] < new_games] + top))
    rng.shuffle(priority)
    out, seen = [], set()
    for h in priority:
        if len(out) >= n_matches:
            break
        others = [o for o in ids if o != h and frozenset((h, o)) not in seen]
        if not others:
            continue
        same = [o for o in others if clusters.get(o) is not None and clusters.get(o) == clusters.get(h)]
        pool = same or others
        partner = min(pool, key=lambda o: abs(by[o] - by[h]) + rng.random() * 1e-6)
        seen.add(frozenset((h, partner)))
        out.append((h, partner))
    return out

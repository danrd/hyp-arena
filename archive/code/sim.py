"""Tournament simulation for ranking many hypotheses with a noisy pairwise judge.

Each hypothesis has two latent scores: promise and feasibility. A judge (a stand-in
for an LLM) compares two hypotheses on both axes per call, with noise and a
position bias. We compare pair-selection strategies by how well the estimated
ranking recovers the truth under a fixed comparison budget.

Run: python -m hyparena.sim
"""
from __future__ import annotations

import numpy as np

AXES = 2  # 0 = promise, 1 = feasibility


def make_population(n: int, rho: float, rng: np.random.Generator) -> np.ndarray:
    """True (n, 2) scores; promise and feasibility are correlated with coefficient rho."""
    cov = np.array([[1.0, rho], [rho, 1.0]])
    return rng.multivariate_normal(np.zeros(2), cov, size=n)


class Judge:
    """Noisy pairwise judge. P(first wins) = sigmoid((diff + bias) / temperature)."""

    def __init__(self, truth: np.ndarray, rng: np.random.Generator,
                 temperature: float = 1.0, position_bias: float = 0.3):
        self.truth, self.rng = truth, rng
        self.temperature, self.position_bias = temperature, position_bias

    def compare(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Return bool (m, 2): True where the item shown first (a) wins on that axis."""
        diff = self.truth[a] - self.truth[b] + self.position_bias
        p = 1.0 / (1.0 + np.exp(-diff / self.temperature))
        return self.rng.random(p.shape) < p


class BradleyTerry:
    """Per-axis Bradley-Terry fit on a dense count matrix, with Fisher-information SE."""

    def __init__(self, n: int):
        self.n = n
        self.wins = np.zeros((AXES, n, n))  # wins[ax, i, j]: times i beat j
        self.games = np.zeros((n, n))       # games[i, j]: times i met j
        self.score = np.zeros((AXES, n))    # log-strength
        self.se = np.full((AXES, n), 10.0)

    def add(self, a: np.ndarray, b: np.ndarray, a_wins: np.ndarray) -> None:
        for ax in range(AXES):
            w = a_wins[:, ax]
            np.add.at(self.wins[ax], (a[w], b[w]), 1)
            np.add.at(self.wins[ax], (b[~w], a[~w]), 1)
        np.add.at(self.games, (a, b), 1)
        np.add.at(self.games, (b, a), 1)

    def fit(self, iters: int = 5) -> None:
        n_ij = self.games  # symmetric by construction
        for ax in range(AXES):
            total_wins = self.wins[ax].sum(1) + 0.5  # virtual draw vs. a unit-strength item
            p = np.exp(self.score[ax])
            for _ in range(iters):
                denom = (n_ij / (p[:, None] + p[None, :])).sum(1) + 1.0 / (p + 1.0)
                p = total_wins / denom
                p /= np.exp(np.log(p).mean())
            self.score[ax] = np.log(p)
            q = p[:, None] * p[None, :] / (p[:, None] + p[None, :]) ** 2
            info = (n_ij * q).sum(1) + p / (p + 1.0) ** 2
            self.se[ax] = 1.0 / np.sqrt(info)

    def combined(self, w: float) -> tuple[np.ndarray, np.ndarray]:
        s = w * self.score[0] + (1 - w) * self.score[1]
        se = np.sqrt((w * self.se[0]) ** 2 + ((1 - w) * self.se[1]) ** 2)
        return s, se


# ---- pair selection strategies: return (m, 2) int array ----

def pairs_random(model, rng, m, k, w):
    a = rng.integers(0, model.n, m)
    b = (a + rng.integers(1, model.n, m)) % model.n
    return np.stack([a, b], 1)


def _neighbour_pairs(idx_sorted, rng, m):
    if rng.random() < 0.5:
        idx_sorted = idx_sorted[1:]
    pairs = idx_sorted[: len(idx_sorted) // 2 * 2].reshape(-1, 2)
    if len(pairs) > m:
        pairs = pairs[rng.choice(len(pairs), m, replace=False)]
    return pairs


def pairs_swiss(model, rng, m, k, w):
    s, _ = model.combined(w)
    order = np.argsort(-(s + rng.normal(0, 0.05, model.n)))
    return _neighbour_pairs(order, rng, m)


def pairs_active(model, rng, m, k, w, explore: float = 0.2, z: float = 2.0):
    """Successive-elimination style: spend most comparisons on items that could still be top-k."""
    s, se = model.combined(w)
    n_explore = int(m * explore)
    explore_pairs = pairs_swiss(model, rng, n_explore, k, w) if n_explore else np.empty((0, 2), int)
    kth_lower = np.sort(s - z * se)[-k]
    cand = np.where(s + z * se >= kth_lower)[0]
    if len(cand) < 4:
        cand = np.argsort(-s)[: max(4, 2 * k)]
    order = cand[np.argsort(-(s[cand] + rng.normal(0, 0.05, len(cand))))]
    focus = _neighbour_pairs(order, rng, m - n_explore)
    return np.concatenate([focus, explore_pairs])


STRATEGIES = {"random": pairs_random, "swiss": pairs_swiss, "active": pairs_active}


# ---- metrics ----

def _ranks(x):
    r = np.empty(len(x)); r[np.argsort(x)] = np.arange(len(x)); return r


def spearman(x, y):
    return float(np.corrcoef(_ranks(x), _ranks(y))[0, 1])


def top_k_recall(est, true, k):
    return len(set(np.argsort(-est)[:k]) & set(np.argsort(-true)[:k])) / k


def run(strategy: str, n=2000, per_item=(2, 4, 8, 16), seed=0, w=0.5, rho=-0.3,
        top_frac=0.05, temperature=1.0, position_bias=0.3, randomize_order=True):
    rng = np.random.default_rng(seed)
    truth = make_population(n, rho, rng)
    judge = Judge(truth, rng, temperature, position_bias)
    model = BradleyTerry(n)
    k = int(n * top_frac)
    true_combined = w * truth[:, 0] + (1 - w) * truth[:, 1]
    batch, done, out = n // 2, 0, {}
    while done < max(per_item) * n:
        pairs = (STRATEGIES[strategy])(model, rng, batch, k, w) if done else pairs_random(model, rng, batch, k, w)
        if randomize_order:  # counter position bias: random A/B order
            flip = rng.random(len(pairs)) < 0.5
            pairs[flip] = pairs[flip][:, ::-1]
        model.add(pairs[:, 0], pairs[:, 1], judge.compare(pairs[:, 0], pairs[:, 1]))
        model.fit()
        done += len(pairs)
        for b in per_item:
            if b not in out and done >= b * n:
                s, _ = model.combined(w)
                out[b] = dict(recall=top_k_recall(s, true_combined, k),
                              rho_all=spearman(s, true_combined),
                              rho_promise=spearman(model.score[0], truth[:, 0]),
                              rho_feas=spearman(model.score[1], truth[:, 1]))
    return out


def main(seeds=3, n=2000):
    for label, kw in [("A/B order randomized", dict()),
                      ("ablation: fixed order (position bias uncorrected)", dict(randomize_order=False))]:
        print(f"\n### {label} (N={n}, top-5% recall on combined score, mean over {seeds} seeds)\n")
        print("| comparisons / hypothesis | " + " | ".join(STRATEGIES) + " |")
        print("|---|" + "---|" * len(STRATEGIES))
        res = {s: [run(s, n=n, seed=i, **kw) for i in range(seeds)] for s in STRATEGIES}
        for b in (2, 4, 8, 16):
            cells = []
            for s in STRATEGIES:
                rec = np.mean([r[b]["recall"] for r in res[s]]); rho = np.mean([r[b]["rho_all"] for r in res[s]])
                cells.append(f"recall {rec:.2f} / ρ {rho:.2f}")
            print(f"| {b} | " + " | ".join(cells) + " |")
        if kw == {}:
            print(f"\nFull pairwise ranking would need {n*(n-1)//2:,} comparisons "
                  f"({(n-1)/2:.0f} per hypothesis); 16 per hypothesis is {16*n:,}.")


if __name__ == "__main__":
    main()

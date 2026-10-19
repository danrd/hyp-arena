"""Aggregation of rule-based indicators under an ordinal importance order: МРСП / АСПИД (Hovanov) in its SMAA-2
form (Lahdelma, Salminen; implementation after Tervonen, Lahdelma 2007). Implements Aggregation_Spec
(docs/spec/aggregation-spec.md).

Model: additive value u(q_i, w) = sum_j w_j q_ij over indicators mapped to [0, 1] (higher is better).
- Cardinal indicators: fixed reference scales (linear or log between fixed bounds, clipped), never min-max over
  the pool, so values and pairwise probabilities do not depend on which other hypotheses are present.
- Ordinal indicators: SMAA-O random monotone mapping of the levels in every iteration (default), or equal steps.
- Unknown values: drawn uniformly over the admissible range in every iteration ("unknown stays unknown").
- Weights: uniform over the set allowed by the preference profile (tiers of importance, equal groups,
  free indicators). Exact fast paths for no information and for complete tiers; hit-and-run otherwise.
Outputs from one pass with common random numbers: expected value, spread, quantiles, pairwise winning
indices, rank acceptabilities, P(top-k), P(best), central weights, confidence factors, Monte Carlo errors."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import numpy as np
import yaml

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "profiles.yaml"


@dataclass(frozen=True)
class IndicatorSpec:
    id: str
    kind: str                                   # "ordinal" | "cardinal"
    levels: tuple = ()                          # ordinal: worst → best
    bounds: tuple = (0.0, 1.0)                  # cardinal: fixed reference scale (raw units)
    log: bool = False                           # cardinal: log scale between the bounds
    higher_is_better: bool = True
    mapping: str = "smaa_o"                     # ordinal: "smaa_o" | "equal_steps"
    note: str = ""

    def scale(self, raw: float) -> float:
        """A known cardinal value on the fixed scale, clipped to [0, 1], oriented higher-is-better."""
        lo, hi = self.bounds
        if self.log:
            raw, lo, hi = math.log(max(raw, 1e-12)), math.log(lo), math.log(hi)
        x = min(1.0, max(0.0, (raw - lo) / (hi - lo)))
        return x if self.higher_is_better else 1.0 - x


@dataclass
class Profile:
    """A named, versioned preference profile: tiers of importance (every indicator of a tier weighs at least
    as much as every indicator of the next tier; "rest" stands for all indicators not listed), groups of
    equally important indicators, and indicators left free (not listed when there is no "rest")."""
    name: str
    version: str = "1"
    tiers: list = field(default_factory=list)
    equal: list = field(default_factory=list)
    description: str = ""

    def resolved_tiers(self, ids: list[str]) -> list[list[str]]:
        listed = {x for t in self.tiers if t != "rest" for x in t}
        out = []
        for t in self.tiers:
            if t == "rest":
                rest = [i for i in ids if i not in listed]
                if rest:
                    out.append(rest)
            else:
                out.append([x for x in t if x in ids])
        return [t for t in out if t]


def load_profiles(path: Union[str, Path] = CONFIG) -> dict[str, Profile]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {name: Profile(name=name, version=str(p.get("version", "1")), tiers=p.get("tiers", []),
                          equal=p.get("equal", []), description=p.get("description", ""))
            for name, p in data["profiles"].items()}


# ---- weights ----

class WeightSampler:
    """Uniform weights on {w >= 0, sum w = 1} restricted by a profile. Exact for no constraints and for tiers
    that cover every indicator (a sorted flat Dirichlet, the top values given to the first tier in random
    order, and so on); hit-and-run (parallel chains) for everything else."""

    def __init__(self, ids: list[str], profile: Optional[Profile], burn_in: int = 500, chains: int = 256):
        self.ids, self.n = ids, len(ids)
        self.profile = profile
        self.tiers = profile.resolved_tiers(ids) if profile else []
        self.equal = [g for g in (profile.equal if profile else []) if len(g) > 1]
        covered = {x for t in self.tiers for x in t}
        if not self.tiers and not self.equal:
            self.mode = "uniform"
        elif covered == set(ids) and not self.equal and len(covered) == sum(len(t) for t in self.tiers):
            self.mode = "tiers"
        else:
            self.mode = "hit_and_run"
            self._setup_har()
        self.burn_in, self.chains = burn_in, chains

    def _setup_har(self):
        # merge equal indicators into one variable; w = M v
        cls = {}
        for g in self.equal:
            root = next((cls[x] for x in g if x in cls), None)
            root = root if root is not None else len(set(cls.values()))
            for x in g:
                cls[x] = root
        nxt = len(set(cls.values()))
        for x in self.ids:
            if x not in cls:
                cls[x] = nxt
                nxt += 1
        self.p = nxt
        self.M = np.zeros((self.n, self.p))
        for j, x in enumerate(self.ids):
            self.M[j, cls[x]] = 1.0
        self.size = self.M.sum(0)
        rows = [-np.eye(self.p)]                                     # v >= 0
        col = {x: j for j, x in enumerate(self.ids)}
        for a_tier, b_tier in zip(self.tiers, self.tiers[1:]):
            for a in a_tier:
                for b in b_tier:
                    g = np.zeros(self.n)
                    g[col[b]], g[col[a]] = 1.0, -1.0                 # w_b - w_a <= 0
                    rows.append((g @ self.M)[None, :])
        self.A = np.vstack(rows)
        # a strictly feasible start: higher base for higher tiers, free indicators in the middle
        base = np.full(self.n, (len(self.tiers) + 1) / 2.0)
        for t, tier in enumerate(self.tiers):
            for x in tier:
                base[col[x]] = len(self.tiers) - t + 0.5
        v = np.array([base[self.M[:, c] > 0].mean() for c in range(self.p)])
        self.v0 = v / (self.size @ v)

    def sample(self, k: int, rng: np.random.Generator) -> np.ndarray:
        if self.mode == "uniform":
            return rng.dirichlet(np.ones(self.n), size=k)
        if self.mode == "tiers":
            w = -np.sort(-rng.dirichlet(np.ones(self.n), size=k), axis=1)
            out = np.empty((k, self.n))
            col = {x: j for j, x in enumerate(self.ids)}
            pos = 0
            for tier in self.tiers:
                block = w[:, pos:pos + len(tier)]
                if len(tier) > 1:
                    block = rng.permuted(block, axis=1)
                for j, x in enumerate(tier):
                    out[:, col[x]] = block[:, j]
                pos += len(tier)
            return out
        return self._hit_and_run(k, rng)

    def _hit_and_run(self, k: int, rng: np.random.Generator) -> np.ndarray:
        C = min(self.chains, k)
        per = math.ceil(k / C)
        thin = max(1, self.p)
        V = np.tile(self.v0, (C, 1))
        out = []
        s = self.size
        for step in range(self.burn_in + per * thin):
            D = rng.standard_normal((C, self.p))
            D -= np.outer(D @ s / (s @ s), s)                       # stay on sum(w) = 1
            AD = D @ self.A.T
            slack = -(V @ self.A.T)                                  # b - A v with b = 0
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = slack / AD
            hi = np.where(AD > 1e-12, ratio, np.inf).min(1)
            lo = np.where(AD < -1e-12, ratio, -np.inf).max(1)
            t = lo + (hi - lo) * rng.random(C)
            V = V + t[:, None] * D
            V = np.maximum(V, 0.0)
            V /= (V @ s)[:, None]
            if step >= self.burn_in and (step - self.burn_in) % thin == thin - 1:
                out.append(V @ self.M.T)
        return np.vstack(out)[:k]


# ---- aggregation ----

@dataclass
class AggregationResult:
    ids: list[str]
    indicators: list[str]
    expected: dict[str, float]
    std: dict[str, float]
    quantiles: dict[str, list[float]]            # 5%, 50%, 95%
    pairwise: dict[str, dict[str, float]]        # P(u_i > u_j) (+ half of ties), for the leading hypotheses
    rank_acceptability: dict[str, list[float]]   # b_i^r for r = 1..R
    p_topk: dict[str, float]
    p_best: dict[str, float]
    central_weights: dict[str, dict[str, float]]
    confidence: dict[str, float]
    order: list[str]
    meta: dict

    def mc_halfwidth(self, p: float) -> float:
        return 1.96 * math.sqrt(max(p * (1 - p), 0.0) / self.meta["K"])


def _ordinal_mapping(m: int, kind: str, k: int, rng: np.random.Generator) -> np.ndarray:
    """(k, m) values of the m levels (worst → best) per iteration."""
    if m == 1:
        return np.ones((k, 1))
    if kind == "equal_steps" or m == 2:
        return np.tile(np.linspace(0, 1, m), (k, 1))
    inner = np.sort(rng.random((k, m - 2)), axis=1)                 # ascending = worst → best
    return np.hstack([np.zeros((k, 1)), inner, np.ones((k, 1))])


def aggregate(values: dict[str, dict[str, object]], indicators: list[IndicatorSpec], profile: Optional[Profile],
              K: int = 10000, seed: int = 0, k_top: int = 5, pairwise_max: int = 50, chunk: int = 1000,
              confidence_draws: int = 2000) -> AggregationResult:
    """`values[h][indicator]`: an ordinal level name, a raw cardinal number, or None (unknown)."""
    ids = list(values)
    m, n = len(ids), len(indicators)
    rng = np.random.default_rng(seed)
    sampler = WeightSampler([s.id for s in indicators], profile)
    W = sampler.sample(K, rng)                                      # drawn first: common to any pool
    # per-indicator data: known ordinal index / known cardinal value / unknown mask
    known_lvl, known_val, unknown = {}, {}, {}
    for j, s in enumerate(indicators):
        col = [values[h].get(s.id) for h in ids]
        unknown[j] = np.array([v is None for v in col])
        if s.kind == "ordinal":
            idx = [s.levels.index(v) if v is not None else 0 for v in col]
            bad = [v for v in col if v is not None and v not in s.levels]
            if bad:
                raise ValueError(f"{s.id}: unknown levels {bad}")
            known_lvl[j] = np.array(idx)
        else:
            known_val[j] = np.array([s.scale(float(v)) if v is not None else 0.0 for v in col])
    U = np.empty((K, m), dtype=np.float64)
    data_rng = np.random.default_rng(seed + 1)                      # data draws separate from weights
    for start in range(0, K, chunk):
        b = min(chunk, K - start)
        Q = np.empty((b, m, n))
        for j, s in enumerate(indicators):
            if s.kind == "ordinal":
                mapping = _ordinal_mapping(len(s.levels), s.mapping, b, data_rng)
                lvl = np.tile(known_lvl[j], (b, 1))
                if unknown[j].any():
                    draw = data_rng.integers(0, len(s.levels), (b, m))
                    lvl = np.where(unknown[j][None, :], draw, lvl)
                Q[:, :, j] = np.take_along_axis(mapping, lvl, axis=1)
            else:
                val = np.tile(known_val[j], (b, 1))
                if unknown[j].any():
                    val = np.where(unknown[j][None, :], data_rng.random((b, m)), val)
                Q[:, :, j] = val
        U[start:start + b] = np.einsum("bmn,bn->bm", Q, W[start:start + b])
    expected, std = U.mean(0), U.std(0)
    q = np.percentile(U, [5, 50, 95], axis=0)
    tie = np.random.default_rng(seed + 2).random(U.shape) * 1e-12   # exact ties share places at random
    ranks = (-(U + tie)).argsort(axis=1).argsort(axis=1)            # 0 = best
    R = min(m, max(k_top, 10))
    acc = np.stack([(ranks == r).mean(0) for r in range(R)], axis=1)   # (m, R)
    p_top = (ranks < k_top).mean(0)
    p_best = acc[:, 0]
    order_idx = np.argsort(-expected)
    head = order_idx[:min(m, pairwise_max)]
    pairwise = {ids[a]: {ids[b]: float((U[:, a] > U[:, b]).mean() + 0.5 * (U[:, a] == U[:, b]).mean())
                         for b in head if b != a} for a in head}       # ties count half
    # central weights: mean weight vector over the iterations where hypothesis i ranks first
    winner = ranks.argmin(axis=1)
    cw = {}
    for i in range(m):
        hit = winner == i
        if hit.any():
            cw[ids[i]] = dict(zip([s.id for s in indicators], W[hit].mean(0).round(4).tolist()))
    # confidence factors (phase 2): central weights fixed, only the data vary
    conf = {}
    contenders = [i for i in order_idx[:20] if ids[i] in cw]
    if contenders:
        sub_vals = {h: values[h] for h in ids}
        for i in contenders:
            wc = np.array(list(cw[ids[i]].values()))
            res = _data_only(sub_vals, ids, indicators, wc, confidence_draws, seed + 7 + i)
            conf[ids[i]] = float((res.argmax(axis=1) == i).mean())
    as_dict = lambda arr: {h: float(arr[i]) for i, h in enumerate(ids)}
    return AggregationResult(
        ids=ids, indicators=[s.id for s in indicators], expected=as_dict(expected), std=as_dict(std),
        quantiles={h: [float(q[0, i]), float(q[1, i]), float(q[2, i])] for i, h in enumerate(ids)},
        pairwise=pairwise, rank_acceptability={h: acc[i].tolist() for i, h in enumerate(ids)},
        p_topk=as_dict(p_top), p_best=as_dict(p_best), central_weights=cw, confidence=conf,
        order=[ids[i] for i in order_idx],
        meta={"K": K, "seed": seed, "k_top": k_top, "weights": sampler.mode,
              "profile": profile.name if profile else None, "profile_version": profile.version if profile else None,
              "mapping": {s.id: s.mapping for s in indicators if s.kind == "ordinal"},
              "scales": {s.id: [*s.bounds, "log" if s.log else "linear"] for s in indicators if s.kind == "cardinal"},
              "mc_halfwidth_max": 1.96 * math.sqrt(0.25 / K)})


def _data_only(values, ids, indicators, w, K, seed) -> np.ndarray:
    """Values u for fixed weights w with only the data (unknowns, ordinal mappings) random."""
    rng = np.random.default_rng(seed)
    m, n = len(ids), len(indicators)
    Q = np.empty((K, m, n))
    for j, s in enumerate(indicators):
        col = [values[h].get(s.id) for h in ids]
        unk = np.array([v is None for v in col])
        if s.kind == "ordinal":
            mapping = _ordinal_mapping(len(s.levels), s.mapping, K, rng)
            lvl = np.tile([s.levels.index(v) if v is not None else 0 for v in col], (K, 1))
            if unk.any():
                lvl = np.where(unk[None, :], rng.integers(0, len(s.levels), (K, m)), lvl)
            Q[:, :, j] = np.take_along_axis(mapping, lvl, axis=1)
        else:
            val = np.tile([s.scale(float(v)) if v is not None else 0.0 for v in col], (K, 1))
            if unk.any():
                val = np.where(unk[None, :], rng.random((K, m)), val)
            Q[:, :, j] = val
    return Q @ w

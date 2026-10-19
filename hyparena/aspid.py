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


@dataclass(frozen=True)
class Prefer:
    """An expert's pairwise choice under a profile (Aggregation_Spec 6a): hypothesis `a` is at least as good as
    (`>=`) or better than (`>`) `b`. Becomes the linear weight constraint sum_j w_j (q_aj - q_bj) >= 0."""
    a: str
    b: str
    op: str = ">="
    by: str = ""
    at: str = ""
    approximate: bool = False                   # set when an unknown value was replaced by its expectation


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
    prefer: list = field(default_factory=list)  # Prefer constraints from expert pairwise choices

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
                          equal=p.get("equal", []), description=p.get("description", ""),
                          prefer=[Prefer(**x) for x in p.get("prefer", [])])
            for name, p in data["profiles"].items()}


# ---- weights ----

class WeightSampler:
    """Uniform weights on {w >= 0, sum w = 1} restricted by a profile. Exact for no constraints and for tiers
    that cover every indicator (a sorted flat Dirichlet, the top values given to the first tier in random
    order, and so on); hit-and-run (parallel chains) for everything else."""

    def __init__(self, ids: list[str], profile: Optional[Profile], burn_in: int = 500, chains: int = 256,
                 extra: Optional[list[np.ndarray]] = None):
        """`extra`: further constraints g·w <= 0 in weight space (expert pairwise choices)."""
        self.ids, self.n = ids, len(ids)
        self.profile = profile
        self.tiers = profile.resolved_tiers(ids) if profile else []
        self.equal = [g for g in (profile.equal if profile else []) if len(g) > 1]
        self.extra = list(extra or [])
        covered = {x for t in self.tiers for x in t}
        if self.extra:
            self.mode = "hit_and_run"
            self._setup_har()
        elif not self.tiers and not self.equal:
            self.mode = "uniform"
        elif covered == set(ids) and not self.equal and len(covered) == sum(len(t) for t in self.tiers):
            self.mode = "tiers"
        else:
            self.mode = "hit_and_run"
            self._setup_har()
        self.burn_in, self.chains = burn_in, chains

    def _setup_har(self):
        self.M, self.size, self.A, self.v0 = constraint_matrix(self.ids, self.tiers, self.equal)
        if self.extra:
            self.A = np.vstack([self.A, *[(g @ self.M)[None, :] for g in self.extra]])
            self.v0 = _interior_point(self.A, self.size)
        self.p = self.M.shape[1]

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


def constraint_matrix(ids: list[str], tiers: list[list[str]], equal: list[list[str]]):
    """(M, size, A, v0): weights w = M v with equal indicators merged into one variable v_c (size_c members);
    rows of A v <= 0 for v >= 0 and the tier order; v0 a strictly feasible start."""
    n = len(ids)
    cls = {}
    for g in equal:
        root = next((cls[x] for x in g if x in cls), None)
        root = root if root is not None else len(set(cls.values()))
        for x in g:
            cls[x] = root
    nxt = len(set(cls.values()))
    for x in ids:
        if x not in cls:
            cls[x] = nxt
            nxt += 1
    M = np.zeros((n, nxt))
    for j, x in enumerate(ids):
        M[j, cls[x]] = 1.0
    size = M.sum(0)
    rows = [-np.eye(nxt)]                                            # v >= 0
    col = {x: j for j, x in enumerate(ids)}
    for a_tier, b_tier in zip(tiers, tiers[1:]):
        for a in a_tier:
            for b in b_tier:
                g = np.zeros(n)
                g[col[b]], g[col[a]] = 1.0, -1.0                     # w_b - w_a <= 0
                rows.append((g @ M)[None, :])
    # a strictly feasible start: higher base for higher tiers, free indicators in the middle
    base = np.full(n, (len(tiers) + 1) / 2.0)
    for t, tier in enumerate(tiers):
        for x in tier:
            base[col[x]] = len(tiers) - t + 0.5
    v = np.array([base[M[:, c] > 0].mean() for c in range(nxt)])
    return M, size, np.vstack(rows), v / (size @ v)


def _interior_point(A: np.ndarray, size: np.ndarray) -> np.ndarray:
    """A point of {A v <= 0, size·v = 1} as deep inside as possible (max t with A_i v + t |A_i| <= 0), the start
    of hit-and-run. Raises ValueError when the set is empty."""
    from scipy.optimize import linprog
    p = A.shape[1]
    norms = np.linalg.norm(A, axis=1)
    res = linprog(c=np.r_[np.zeros(p), -1.0], A_ub=np.c_[A, norms], b_ub=np.zeros(len(A)),
                  A_eq=np.r_[size, 0.0][None, :], b_eq=[1.0], bounds=[(None, None)] * p + [(None, 1.0)],
                  method="highs")
    if res.status != 0 or res.x[-1] < -1e-12:
        raise ValueError("the preference constraints leave no admissible weights")
    return np.maximum(res.x[:p], 0.0)


def expected_value(spec: IndicatorSpec, value) -> tuple[float, bool]:
    """(expected mapped value, approximate): an unknown gives the middle of its range (approximate); an ordinal
    level gives the mean of the SMAA-O mapping, which equals the equal-step value."""
    if value is None:
        return 0.5, True
    if spec.kind == "ordinal":
        m = len(spec.levels)
        return (spec.levels.index(value) / (m - 1) if m > 1 else 1.0), False
    return spec.scale(float(value)), False


def preference_rows(prefer: list[Prefer], values: dict, indicators: list[IndicatorSpec]) -> list[tuple[Prefer, np.ndarray]]:
    """Each choice as a row g with g·w <= 0 (Aggregation_Spec 6a, MVP: unknowns at their expected value)."""
    out = []
    for c in prefer:
        if c.a not in values or c.b not in values:
            raise KeyError(f"preference {c.a} {c.op} {c.b}: hypothesis not in the ranked pool")
        qa = [expected_value(s, values[c.a].get(s.id)) for s in indicators]
        qb = [expected_value(s, values[c.b].get(s.id)) for s in indicators]
        approx = any(x[1] for x in qa + qb)
        dq = np.array([x[0] for x in qa]) - np.array([x[0] for x in qb])
        out.append((Prefer(c.a, c.b, c.op, c.by, c.at, approx or c.approximate), -dq))
    return out


@dataclass
class Feasibility:
    feasible: bool
    conflicting: list = field(default_factory=list)   # a minimal set of conflicting choices (criterion_gap)


def check_feasible(profile: Profile, values: dict, indicators: list[IndicatorSpec]) -> Feasibility:
    """Do the profile's tiers and the expert choices leave any admissible weights? Strict choices (">") must
    hold with a positive margin. When not, a minimal conflicting subset of the choices (deletion filter)."""
    rows = preference_rows(profile.prefer, values, indicators)
    if _feasible(profile, indicators, rows):
        return Feasibility(True)
    core = list(rows)
    for r in list(core):
        trial = [x for x in core if x is not r]
        if not _feasible(profile, indicators, trial):
            core = trial
    return Feasibility(False, [c for c, _ in core])


def _feasible(profile: Profile, indicators: list[IndicatorSpec], rows) -> bool:
    from scipy.optimize import linprog
    ids = [s.id for s in indicators]
    M, size, A, _ = constraint_matrix(ids, profile.resolved_tiers(ids), [g for g in profile.equal if len(g) > 1])
    strict = [np.r_[g @ M, 1.0] for c, g in rows if c.op == ">"]       # g·w + t <= 0: holds with margin t
    weak = [np.r_[g @ M, 0.0] for c, g in rows if c.op != ">"]
    A_ub = np.vstack([np.c_[A, np.zeros(len(A))], *[r[None, :] for r in weak + strict]])
    res = linprog(c=np.r_[np.zeros(M.shape[1]), -1.0], A_ub=A_ub, b_ub=np.zeros(len(A_ub)),
                  A_eq=np.r_[size, 0.0][None, :], b_eq=[1.0], bounds=[(None, None)] * M.shape[1] + [(0.0, 1.0)],
                  method="highs")
    if res.status != 0:
        return False
    return not strict or res.x[-1] > 1e-9


def next_pair(result: "AggregationResult", threshold: float = 0.5) -> Optional[tuple[str, str]]:
    """The pair to ask an expert next (Aggregation_Spec 6a): among hypotheses with P(top-k) >= threshold, the
    one whose pairwise winning index is closest to 0.5 (ties: the better expected values first)."""
    top = [h for h in result.order if result.p_topk.get(h, 0.0) >= threshold]
    best, pair = None, None
    for i, a in enumerate(top):
        for b in top[i + 1:]:
            p = result.pairwise.get(a, {}).get(b)
            if p is None:
                continue
            d = abs(p - 0.5)
            if best is None or d < best - 1e-12:
                best, pair = d, (a, b)
    return pair


class InfeasiblePreferences(ValueError):
    """criterion_gap: the expert choices contradict each other (or the profile) under the indicators."""

    def __init__(self, conflicting: list[Prefer]):
        self.conflicting = conflicting
        super().__init__("criterion_gap: conflicting expert choices: " +
                         "; ".join(f"{c.a} {c.op} {c.b} ({c.by})" for c in conflicting))


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
    prefs = preference_rows(profile.prefer, values, indicators) if profile and profile.prefer else []
    if prefs:
        feas = check_feasible(profile, values, indicators)
        if not feas.feasible:
            raise InfeasiblePreferences(feas.conflicting)
    sampler = WeightSampler([s.id for s in indicators], profile, extra=[g for _, g in prefs])
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
              "mc_halfwidth_max": 1.96 * math.sqrt(0.25 / K),
              # expert choices: how often the drawn data still violate them (SMAA-O mappings and unknowns
              # vary per draw; the weights satisfy them at the expected values)
              "prefer": [{"a": c.a, "op": c.op, "b": c.b, "by": c.by, "at": c.at, "approximate": c.approximate,
                          "violated_share": float((U[:, ids.index(c.a)] < U[:, ids.index(c.b)]).mean())}
                         for c, _ in prefs]})


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

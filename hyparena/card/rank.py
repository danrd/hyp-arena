"""Ordering of search candidates before reading, by code: BM25 of the query terms against title and abstract (the
search benchmark, specs/benchmark-search-2026-11-12.yaml, free_experiments_2026_11_14: recall 0.20 -> 0.34 at 20 per
claim over the round-robin merge of the queries)."""
from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("and or not the of in on for with to a an by from tiab mesh mh pt majr title abstract terms all fields nm sh la "
           "review humans human english".split())


def query_terms(queries: list[str]) -> list[str]:
    """The words of the queries, field tags and operators removed."""
    words = []
    for q in queries:
        q = re.sub(r"\[[^\]]*\]", " ", q)
        words += [w for w in re.findall(r"[a-z][a-z0-9-]{2,}", q.lower()) if w not in STOP]
    return list(dict.fromkeys(words))


def tokens(s: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9-]{2,}", (s or "").lower())


def bm25(terms: list[str], docs: dict[str, list[str]]) -> list[str]:
    """Document keys, best first (k1 1.2, b 0.75); ties keep the input order."""
    n = len(docs) or 1
    avg = sum(len(d) for d in docs.values()) / n or 1
    df = Counter(t for d in docs.values() for t in set(d))
    score = {}
    for p, d in docs.items():
        tf = Counter(d)
        score[p] = sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avg))
                       for t in terms if t in tf)
    return sorted(docs, key=lambda p: -score[p])


def select(order: list[str], scores: dict[str, int], fill: int = 10, cap: int = 20) -> list[str]:
    """The papers to read from the relevance ratings (0-3): every paper rated 3, filled up to `fill` with papers rated 2,
    at most `cap`; within a rating the code order. (Search benchmark, filter_experiment_2026_11_14: recall 0.48 with a
    median of 43 papers per hypothesis, against 0.33 with 99 for the earlier search.)"""
    three = [p for p in order if scores.get(p) == 3]
    two = [p for p in order if scores.get(p) == 2]
    return (three + two[:max(0, fill - len(three))])[:cap]

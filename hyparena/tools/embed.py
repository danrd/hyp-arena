"""Embedding interface plus a dependency-free hashing embedder (a stand-in for a real model)."""
from __future__ import annotations

import re
import zlib
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...   # (n, d), rows L2-normalized


class HashingEmbedder:
    """Bag-of-words hashed into `dim` buckets. Captures word overlap only."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim))
        for i, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                out[i, zlib.crc32(word.encode()) % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1.0, norms)

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


SAPBERT_REPO = "Xenova/SapBERT-from-PubMedBERT-fulltext"     # ONNX export of cambridgeltl/SapBERT (Apache-2.0)


class SapBertEmbedder:
    """SapBERT (Liu et al. 2021, arXiv:2010.11784): PubMedBERT trained so that synonyms of one UMLS concept lie
    close together, i.e. made for biomedical entity names. Runs locally (ONNX, int8, about 110 MB, downloaded
    once into the Hugging Face cache); the [CLS] vector, L2-normalized. Needs onnxruntime, tokenizers and
    huggingface_hub (`pip install -e ".[embed]"`)."""

    def __init__(self, model_file: str = "onnx/model_quantized.onnx", max_tokens: int = 32):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
        self.tokenizer = Tokenizer.from_file(hf_hub_download(SAPBERT_REPO, "tokenizer.json"))
        self.tokenizer.enable_truncation(max_tokens)
        self.tokenizer.enable_padding()
        self.session = ort.InferenceSession(hf_hub_download(SAPBERT_REPO, model_file))
        self.inputs = {i.name for i in self.session.get_inputs()}

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 768))
        out = []
        for i in range(0, len(texts), 64):
            enc = self.tokenizer.encode_batch(texts[i:i + 64])
            feed = {"input_ids": [e.ids for e in enc], "attention_mask": [e.attention_mask for e in enc],
                    "token_type_ids": [e.type_ids for e in enc]}
            feed = {k: np.array(v, dtype=np.int64) for k, v in feed.items() if k in self.inputs}
            out.append(self.session.run(None, feed)[0][:, 0, :])
        x = np.concatenate(out)
        return x / np.linalg.norm(x, axis=1, keepdims=True)

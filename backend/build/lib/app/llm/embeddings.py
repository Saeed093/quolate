"""Embeddings seam. All embedding calls go through here.

TODO(cloud): point at a hosted embedding API implementing the same interface.
"""
from __future__ import annotations

import hashlib
import math

from app.config import settings

DIM = settings.embedding_dim


def _mock_embed_one(text: str) -> list[float]:
    """Deterministic pseudo-embedding (unit-normalised) for tests.

    Uses hashed token bucketing so semantically-overlapping texts (shared words)
    produce higher cosine similarity than unrelated texts.
    """
    vec = [0.0] * DIM
    tokens = [t for t in text.lower().split() if t]
    for tok in tokens:
        h = int(hashlib.sha256(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % DIM
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        vec[0] = 1.0
        return vec
    return [v / norm for v in vec]


def embed_texts(texts: list[str], timeout: float | None = None) -> list[list[float]]:
    if not texts:
        return []
    if settings.llm_is_mock:
        return [_mock_embed_one(t) for t in texts]

    from openai import OpenAI

    effective_timeout = timeout if timeout is not None else settings.llm_fast_timeout_seconds
    client = OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=effective_timeout,
    )
    resp = client.embeddings.create(model=settings.embedding_model, input=texts)
    return [d.embedding for d in resp.data]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]

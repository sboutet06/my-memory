"""Cross-encoder reranker — addresses retrieval variance deterministically.

LightRAG's retrieval is vector-similarity only: different runs surface
different chunks and answers drift. A cross-encoder scores (query, doc)
pairs directly, giving a stable ordering the LLM sees every time.

Model is multilingual by default (matches the embedding stack). Env-
overridable so any domain can pick a different reranker.
"""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Any

from sentence_transformers import CrossEncoder

# Multilingual cross-encoder, ~117 MB — light on RAM for dev machines.
# Upgrade to `BAAI/bge-reranker-v2-m3` (SOTA, ~568 MB) via
# `EXTRACTION_RERANK_MODEL` when accuracy matters more than footprint.
DEFAULT_RERANK_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


def _rerank_model_name() -> str:
    return os.environ.get("EXTRACTION_RERANK_MODEL", DEFAULT_RERANK_MODEL)


@lru_cache(maxsize=4)
def _get_cross_encoder(model_name: str) -> CrossEncoder:
    return CrossEncoder(model_name)


def _format_results(
    scores: list[float] | Any,
    top_n: int | None = None,
) -> list[dict]:
    """Shape raw scores into LightRAG's expected index-based output.

    Returns `[{"index": i, "relevance_score": s}, ...]` sorted by score
    descending, optionally truncated to `top_n`.
    """
    indexed = [
        {"index": i, "relevance_score": float(s)}
        for i, s in enumerate(list(scores))
    ]
    indexed.sort(key=lambda r: r["relevance_score"], reverse=True)
    if top_n is not None and top_n >= 0:
        indexed = indexed[:top_n]
    return indexed


async def rerank_func(
    query: str,
    documents: list[str],
    top_n: int | None = None,
) -> list[dict]:
    """LightRAG-compatible rerank function backed by a local CrossEncoder."""
    if not documents:
        return []
    model = _get_cross_encoder(_rerank_model_name())
    pairs = [(query, doc) for doc in documents]
    loop = asyncio.get_running_loop()
    scores = await loop.run_in_executor(None, lambda: model.predict(pairs))
    return _format_results(scores, top_n=top_n)

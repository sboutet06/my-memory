"""LLM + embedding callables passed to LightRAG.

- LLM: any OpenAI-compatible chat endpoint (default: OpenRouter).
- Embeddings: local `sentence-transformers` model (sovereign by default).
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

import numpy as np
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc
from sentence_transformers import SentenceTransformer

from extraction.config import ExtractionConfig


@lru_cache(maxsize=4)
def _get_embed_model(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)


def make_llm_func(config: ExtractionConfig):
    api_key = config.require_api_key()

    async def llm_model_func(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list | None = None,
        keyword_extraction: bool = False,
        **kwargs,
    ) -> str:
        return await openai_complete_if_cache(
            config.llm_model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            api_key=api_key,
            base_url=config.base_url,
            **kwargs,
        )

    return llm_model_func


def make_embedding_func(config: ExtractionConfig) -> EmbeddingFunc:
    model = _get_embed_model(config.embed_model)

    async def embed(texts: list[str]) -> np.ndarray:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: model.encode(
                texts, convert_to_numpy=True, normalize_embeddings=True
            ),
        )

    return EmbeddingFunc(
        embedding_dim=config.embed_dim,
        func=embed,
    )

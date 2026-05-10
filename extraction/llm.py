"""LLM + embedding callables passed to LightRAG.

- LLM: any OpenAI-compatible chat endpoint (default: OpenRouter).
- Embeddings: local `sentence-transformers` model (sovereign by default).
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path

import numpy as np
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc
from sentence_transformers import SentenceTransformer

from extraction.cache import EXTRACTOR_VERSION, cached_completion
from extraction.config import ExtractionConfig

# Default location for the fingerprint cache. Lives under
# `extraction_store/` so it's covered by the same .gitignore rule as
# the rest of LightRAG's working dir; safe to git-clean alongside.
DEFAULT_EXTRACT_CACHE_DIR = Path("extraction_store") / "cache"


@lru_cache(maxsize=4)
def _get_embed_model(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)


def make_llm_func(
    config: ExtractionConfig,
    *,
    cache_dir: Path | None = None,
):
    """Build the LightRAG `llm_model_func` callable.

    `cache_dir=None` (default) routes through `extraction.cache` keyed on
    fingerprint(extractor_version, model_id, prompt, system_prompt,
    history) so re-extraction with unchanged code is bit-identical and
    free. Pass `cache_dir=Path("/nul")` or override at the call site if
    you need bypass behaviour (e.g. live benchmark sweeps).
    """
    api_key = config.require_api_key()
    if cache_dir is None:
        cache_dir = DEFAULT_EXTRACT_CACHE_DIR

    async def underlying(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list | None = None,
        **kwargs,
    ) -> str:
        # Default to 0.0 so eval metrics stay reproducible across runs
        # (OpenRouter routes same call to different provider instances
        # with different seeds otherwise). Override via config.temperature
        # or EXTRACTION_TEMPERATURE env var for sampling experiments.
        kwargs.setdefault("temperature", config.temperature)
        # Phase 8b.4: OpenRouter accepts `provider.order=[...]` to pin
        # which upstream serves the request. Used by the Mistral / EU
        # routing path for sovereign-aligned extraction. The openai
        # client forwards extra_body verbatim into the JSON request body.
        if config.provider_order:
            extra_body = dict(kwargs.get("extra_body") or {})
            extra_body.setdefault("provider", {"order": list(config.provider_order)})
            kwargs["extra_body"] = extra_body
        return await openai_complete_if_cache(
            config.llm_model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            api_key=api_key,
            base_url=config.base_url,
            **kwargs,
        )

    async def llm_model_func(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list | None = None,
        keyword_extraction: bool = False,
        **kwargs,
    ) -> str:
        return await cached_completion(
            underlying,
            cache_dir=cache_dir,
            prompt=prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            model_id=config.llm_model,
            extractor_version=EXTRACTOR_VERSION,
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

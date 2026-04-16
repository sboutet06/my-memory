"""Extraction configuration — defaults + env overrides.

All knobs are env-overridable so the module is not tied to the current
personal-docs corpus. Entity types are deliberately universal; forcing
French-admin-specific types (`impot`, `notaire`, …) would overfit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

# Default entity taxonomy — small, universal, domain-agnostic.
_DEFAULT_ENTITY_TYPES: tuple[str, ...] = (
    "person",
    "organization",
    "location",
    "date",
    "amount",
    "document",
    "identifier",
    "concept",
)

_DEFAULT_LLM_MODEL = "google/gemini-2.5-flash"
_DEFAULT_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_DEFAULT_EMBED_DIM = 384
_DEFAULT_LANGUAGE = "auto"
_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _parse_csv_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class ExtractionConfig:
    llm_model: str = _DEFAULT_LLM_MODEL
    embed_model: str = _DEFAULT_EMBED_MODEL
    embed_dim: int = _DEFAULT_EMBED_DIM
    language: str = _DEFAULT_LANGUAGE
    base_url: str = _DEFAULT_BASE_URL
    entity_types: list[str] = field(default_factory=lambda: list(_DEFAULT_ENTITY_TYPES))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ExtractionConfig":
        """Build a config from an env-like mapping. Pass `os.environ` in prod."""
        env = env if env is not None else os.environ
        raw_types = env.get("EXTRACTION_ENTITY_TYPES", "")
        types = _parse_csv_list(raw_types) if raw_types else list(_DEFAULT_ENTITY_TYPES)
        return cls(
            llm_model=env.get("EXTRACTION_LLM_MODEL", _DEFAULT_LLM_MODEL),
            embed_model=env.get("EXTRACTION_EMBED_MODEL", _DEFAULT_EMBED_MODEL),
            embed_dim=int(env.get("EXTRACTION_EMBED_DIM", str(_DEFAULT_EMBED_DIM))),
            language=env.get("EXTRACTION_LANGUAGE", _DEFAULT_LANGUAGE),
            base_url=env.get("EXTRACTION_BASE_URL", _DEFAULT_BASE_URL),
            entity_types=types,
        )

    def addon_params(self) -> dict:
        """Params injected into LightRAG's `addon_params` constructor arg."""
        return {
            "entity_types": list(self.entity_types),
            "language": self.language,
        }

    def require_api_key(self) -> str:
        key = os.environ.get("OPEN_ROUTER_API_KEY")
        if not key:
            raise RuntimeError(
                "OPEN_ROUTER_API_KEY is not set. Add it to .env or export it."
            )
        return key

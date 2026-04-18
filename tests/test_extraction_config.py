"""Unit tests for extraction config (env overrides + defaults)."""
from __future__ import annotations

import pytest

from extraction.config import ExtractionConfig


def test_defaults_are_universal_not_french_specific() -> None:
    cfg = ExtractionConfig.from_env({})
    # Types must be domain-agnostic to avoid overfitting to the current corpus.
    forbidden = {"impot", "notaire", "facture", "passeport", "compromis"}
    assert not (set(cfg.entity_types) & forbidden), cfg.entity_types
    # Minimum universal set covered.
    required = {"person", "organization", "location", "date", "concept"}
    assert required <= set(cfg.entity_types)


def test_entity_types_overridable_via_env() -> None:
    cfg = ExtractionConfig.from_env(
        {"EXTRACTION_ENTITY_TYPES": "person,organization,product"}
    )
    assert cfg.entity_types == ["person", "organization", "product"]


def test_entity_types_env_strips_whitespace_and_blanks() -> None:
    cfg = ExtractionConfig.from_env(
        {"EXTRACTION_ENTITY_TYPES": " person ,, organization , ,location"}
    )
    assert cfg.entity_types == ["person", "organization", "location"]


def test_llm_model_overridable() -> None:
    cfg = ExtractionConfig.from_env({"EXTRACTION_LLM_MODEL": "anthropic/claude-haiku-4.5"})
    assert cfg.llm_model == "anthropic/claude-haiku-4.5"


def test_embed_model_overridable() -> None:
    cfg = ExtractionConfig.from_env({"EXTRACTION_EMBED_MODEL": "BAAI/bge-m3"})
    assert cfg.embed_model == "BAAI/bge-m3"


def test_language_default_is_auto_not_hardcoded_french() -> None:
    """Forcing a language would overfit to the current corpus — default must be neutral."""
    cfg = ExtractionConfig.from_env({})
    assert cfg.language.lower() in {"auto", "english", "en", ""}


def test_language_overridable() -> None:
    cfg = ExtractionConfig.from_env({"EXTRACTION_LANGUAGE": "French"})
    assert cfg.language == "French"


def test_addon_params_injects_types_and_language() -> None:
    cfg = ExtractionConfig.from_env({"EXTRACTION_LANGUAGE": "French"})
    params = cfg.addon_params()
    assert params["entity_types"] == cfg.entity_types
    assert params["language"] == "French"


def test_missing_api_key_raises_on_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPEN_ROUTER_API_KEY", raising=False)
    cfg = ExtractionConfig.from_env({})
    with pytest.raises(RuntimeError, match="OPEN_ROUTER_API_KEY"):
        cfg.require_api_key()


def test_temporal_user_prompt_has_generic_default() -> None:
    cfg = ExtractionConfig.from_env({})
    prompt = cfg.temporal_user_prompt.lower()
    # Generic time-varying categories — NOT specific to the personal-doc corpus.
    assert "address" in prompt
    assert "employer" in prompt
    # No corpus-leak: no French-admin-specific terms.
    forbidden = ["boutet", "montauroux", "roquefort", "mylène", "sébastien"]
    assert not any(w in prompt for w in forbidden)


def test_temporal_user_prompt_overridable() -> None:
    cfg = ExtractionConfig.from_env({"EXTRACTION_TEMPORAL_USER_PROMPT": "Answer briefly."})
    assert cfg.temporal_user_prompt == "Answer briefly."


def test_temperature_default_is_zero_for_reproducibility() -> None:
    cfg = ExtractionConfig.from_env({})
    assert cfg.temperature == 0.0


def test_temperature_overridable_via_env() -> None:
    cfg = ExtractionConfig.from_env({"EXTRACTION_TEMPERATURE": "0.7"})
    assert cfg.temperature == 0.7

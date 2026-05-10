"""Tests for `make_llm_func` — Phase 8b.4 provider routing.

The wrapper applies sovereign-routable provider pinning by injecting
`extra_body.provider.order` into the OpenAI-compatible request body.
We mock `openai_complete_if_cache` to capture the kwargs without making
real HTTP calls. Sync drivers via `asyncio.run` follow the existing
project pattern (test_benchmarks.py).
"""
from __future__ import annotations

import asyncio

import pytest

from extraction import llm as llm_mod
from extraction.config import ExtractionConfig


@pytest.fixture
def fake_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "sk-fake-test-key")


@pytest.fixture
def captured_call(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace openai_complete_if_cache with a recorder."""
    recorder: dict = {"kwargs": None, "args": None, "called": False}

    async def fake(*args, **kwargs):
        recorder["args"] = args
        recorder["kwargs"] = kwargs
        recorder["called"] = True
        return "stub response"

    monkeypatch.setattr(llm_mod, "openai_complete_if_cache", fake)
    return recorder


def _run(coro):
    return asyncio.run(coro)


def test_no_provider_order_omits_extra_body(fake_api_key, captured_call) -> None:
    """Default config = no provider pinning = no `extra_body` injection."""
    cfg = ExtractionConfig.from_env({})
    func = llm_mod.make_llm_func(cfg)

    _run(func("hi"))

    assert captured_call["called"]
    assert "extra_body" not in captured_call["kwargs"]


def test_provider_order_injects_extra_body(fake_api_key, captured_call) -> None:
    cfg = ExtractionConfig.from_env({"EXTRACTION_PROVIDER_ORDER": "mistral"})
    func = llm_mod.make_llm_func(cfg)

    _run(func("hi"))

    extra = captured_call["kwargs"].get("extra_body")
    assert extra is not None
    assert extra["provider"]["order"] == ["mistral"]


def test_provider_order_preserves_caller_extra_body(fake_api_key, captured_call) -> None:
    """If the caller passes extra_body already, provider routing merges
    instead of overwriting unrelated keys."""
    cfg = ExtractionConfig.from_env({"EXTRACTION_PROVIDER_ORDER": "mistral"})
    func = llm_mod.make_llm_func(cfg)

    _run(func("hi", extra_body={"unrelated": "value"}))

    extra = captured_call["kwargs"].get("extra_body")
    assert extra["unrelated"] == "value"
    assert extra["provider"]["order"] == ["mistral"]


def test_provider_order_does_not_overwrite_caller_provider(
    fake_api_key, captured_call,
) -> None:
    """`setdefault` semantics: a caller's explicit `provider` wins."""
    cfg = ExtractionConfig.from_env({"EXTRACTION_PROVIDER_ORDER": "mistral"})
    func = llm_mod.make_llm_func(cfg)

    _run(func("hi", extra_body={"provider": {"order": ["together"]}}))

    extra = captured_call["kwargs"]["extra_body"]
    assert extra["provider"]["order"] == ["together"]


def test_ranked_provider_order_passes_through(fake_api_key, captured_call) -> None:
    cfg = ExtractionConfig.from_env(
        {"EXTRACTION_PROVIDER_ORDER": "mistral,together,openai"},
    )
    func = llm_mod.make_llm_func(cfg)

    _run(func("hi"))

    assert captured_call["kwargs"]["extra_body"]["provider"]["order"] == [
        "mistral", "together", "openai",
    ]


def test_temperature_still_defaulted_to_zero(fake_api_key, captured_call) -> None:
    """Provider routing must not break the existing temp=0 reproducibility
    contract."""
    cfg = ExtractionConfig.from_env({"EXTRACTION_PROVIDER_ORDER": "mistral"})
    func = llm_mod.make_llm_func(cfg)

    _run(func("hi"))

    assert captured_call["kwargs"]["temperature"] == 0.0


def test_model_id_forwards_from_config(fake_api_key, captured_call) -> None:
    cfg = ExtractionConfig.from_env(
        {"EXTRACTION_LLM_MODEL": "mistralai/mistral-small-latest"},
    )
    func = llm_mod.make_llm_func(cfg)

    _run(func("hi"))

    # First positional arg of openai_complete_if_cache is the model id.
    assert captured_call["args"][0] == "mistralai/mistral-small-latest"

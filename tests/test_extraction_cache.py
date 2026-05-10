"""Phase 8b.3 — fingerprint-keyed extraction cache.

The cache sits at the LLM-call boundary. Key is
SHA-256(extractor_version | model_id | prompt | system_prompt |
history_json). Cache hits skip the underlying LLM call entirely;
re-extracting with unchanged code/model/prompt is bit-identical and
free.

Bust dimensions (any change → miss):
- prompt content (already what LightRAG's internal cache keys on, but
  we still want this on our side so we own the source of truth).
- model_id (Gemini → Mistral = fresh extraction).
- extractor_version (we bump this constant when we touch prompts /
  extraction logic).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from extraction.cache import (
    EXTRACTOR_VERSION,
    cached_completion,
    clear_cache,
    fingerprint,
)


def _run(coro):
    return asyncio.run(coro)


# --- fingerprint stability ------------------------------------------------


def test_fingerprint_deterministic_across_calls() -> None:
    fp1 = fingerprint(
        prompt="p", system_prompt="s", history=[], model_id="m", extractor_version="v",
    )
    fp2 = fingerprint(
        prompt="p", system_prompt="s", history=[], model_id="m", extractor_version="v",
    )
    assert fp1 == fp2


def test_fingerprint_changes_with_prompt() -> None:
    f1 = fingerprint(prompt="A", system_prompt=None, history=[], model_id="m", extractor_version="v")
    f2 = fingerprint(prompt="B", system_prompt=None, history=[], model_id="m", extractor_version="v")
    assert f1 != f2


def test_fingerprint_changes_with_model() -> None:
    f1 = fingerprint(prompt="p", system_prompt=None, history=[], model_id="gemini", extractor_version="v")
    f2 = fingerprint(prompt="p", system_prompt=None, history=[], model_id="mistral", extractor_version="v")
    assert f1 != f2


def test_fingerprint_changes_with_extractor_version() -> None:
    f1 = fingerprint(prompt="p", system_prompt=None, history=[], model_id="m", extractor_version="1.0")
    f2 = fingerprint(prompt="p", system_prompt=None, history=[], model_id="m", extractor_version="1.1")
    assert f1 != f2


def test_fingerprint_changes_with_system_prompt() -> None:
    f1 = fingerprint(prompt="p", system_prompt="sa", history=[], model_id="m", extractor_version="v")
    f2 = fingerprint(prompt="p", system_prompt="sb", history=[], model_id="m", extractor_version="v")
    assert f1 != f2


def test_fingerprint_changes_with_history() -> None:
    f1 = fingerprint(prompt="p", system_prompt=None, history=[], model_id="m", extractor_version="v")
    f2 = fingerprint(
        prompt="p", system_prompt=None,
        history=[{"role": "user", "content": "x"}],
        model_id="m", extractor_version="v",
    )
    assert f1 != f2


# --- cached_completion wraps async call ----------------------------------


def test_cache_miss_calls_underlying(tmp_path: Path) -> None:
    calls = {"n": 0}

    async def under(prompt, system_prompt=None, history_messages=None, **kw):
        calls["n"] += 1
        return f"resp:{prompt}"

    async def go():
        return await cached_completion(
            under,
            cache_dir=tmp_path / "cache",
            prompt="hello",
            model_id="m",
            extractor_version=EXTRACTOR_VERSION,
        )

    out = _run(go())
    assert out == "resp:hello"
    assert calls["n"] == 1


def test_cache_hit_skips_underlying(tmp_path: Path) -> None:
    calls = {"n": 0}

    async def under(prompt, system_prompt=None, history_messages=None, **kw):
        calls["n"] += 1
        return f"resp:{prompt}"

    async def go():
        first = await cached_completion(
            under,
            cache_dir=tmp_path / "cache",
            prompt="hello",
            model_id="m",
            extractor_version="v",
        )
        second = await cached_completion(
            under,
            cache_dir=tmp_path / "cache",
            prompt="hello",
            model_id="m",
            extractor_version="v",
        )
        return first, second

    a, b = _run(go())
    assert a == b == "resp:hello"
    assert calls["n"] == 1  # second call hit the cache


def test_cache_busts_on_model_change(tmp_path: Path) -> None:
    calls = {"n": 0}

    async def under(prompt, **kw):
        calls["n"] += 1
        return f"resp:{kw.get('_marker', prompt)}"

    async def go():
        a = await cached_completion(
            under, cache_dir=tmp_path / "cache",
            prompt="p", model_id="gemini", extractor_version="v",
        )
        b = await cached_completion(
            under, cache_dir=tmp_path / "cache",
            prompt="p", model_id="mistral", extractor_version="v",
        )
        return a, b

    _run(go())
    assert calls["n"] == 2  # different model → different cache file


def test_cache_busts_on_extractor_version(tmp_path: Path) -> None:
    calls = {"n": 0}

    async def under(prompt, **kw):
        calls["n"] += 1
        return "r"

    async def go():
        await cached_completion(
            under, cache_dir=tmp_path / "cache",
            prompt="p", model_id="m", extractor_version="1.0",
        )
        await cached_completion(
            under, cache_dir=tmp_path / "cache",
            prompt="p", model_id="m", extractor_version="2.0",
        )

    _run(go())
    assert calls["n"] == 2


def test_cache_persists_to_disk(tmp_path: Path) -> None:
    async def under(prompt, **kw):
        return "stored response"

    async def go():
        await cached_completion(
            under, cache_dir=tmp_path / "cache",
            prompt="p", model_id="m", extractor_version="v",
        )

    _run(go())

    files = list((tmp_path / "cache").glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["response"] == "stored response"
    assert payload["model_id"] == "m"
    assert payload["extractor_version"] == "v"
    assert payload["prompt"] == "p"


def test_corrupt_cache_file_falls_back_to_call(tmp_path: Path) -> None:
    """A cache file that fails to parse is treated as a miss + re-extracted."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    fp = fingerprint(prompt="p", system_prompt=None, history=[], model_id="m", extractor_version="v")
    (cache_dir / f"{fp}.json").write_text("{not json", encoding="utf-8")

    calls = {"n": 0}

    async def under(prompt, **kw):
        calls["n"] += 1
        return "recovered"

    async def go():
        return await cached_completion(
            under, cache_dir=cache_dir,
            prompt="p", model_id="m", extractor_version="v",
        )

    out = _run(go())
    assert out == "recovered"
    assert calls["n"] == 1


def test_clear_cache_removes_files(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"

    async def under(prompt, **kw):
        return "r"

    async def populate():
        await cached_completion(
            under, cache_dir=cache_dir,
            prompt="p1", model_id="m", extractor_version="v",
        )
        await cached_completion(
            under, cache_dir=cache_dir,
            prompt="p2", model_id="m", extractor_version="v",
        )

    _run(populate())
    assert len(list(cache_dir.glob("*.json"))) == 2

    removed = clear_cache(cache_dir)
    assert removed == 2
    assert list(cache_dir.glob("*.json")) == []


def test_clear_cache_on_missing_dir_is_zero(tmp_path: Path) -> None:
    assert clear_cache(tmp_path / "nonexistent") == 0

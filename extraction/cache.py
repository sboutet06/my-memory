"""Fingerprint-keyed extraction cache — Phase 8b.3.

Caches LLM responses at the call boundary, keyed on a SHA-256 fingerprint
of (extractor_version, model_id, prompt, system_prompt, history). Stored
one JSON file per fingerprint under `extraction_store/cache/`. Re-running
extraction with unchanged code/model/prompts is a sequence of cache hits
and costs $0.

Charter §3.8b — closes the "no version-keyed cache" gap promoted into
v0.5 by the 2026-05-10 premortem. LightRAG's own llm_response_cache
keys on prompt content alone and lives in its working dir; ours keys
on the richer fingerprint and lives at the application layer so we
own the source of truth.

Bust dimensions:
- prompt content (most often what changes between runs)
- model_id (Gemini → Mistral = full refresh)
- extractor_version (bumped by hand when extraction prompts / logic
  change in a way that should invalidate prior responses)
- system_prompt / history_messages (rarely changed but capture the
  full call context, so two callers using different system prompts
  do not poison each other's cache)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# Bump manually when extraction-side prompts or pipeline behavior change
# in a way that should invalidate cached LLM responses. Cache entries
# stamped with an older value will simply miss on lookup — the old files
# stay on disk for audit unless cleared by hand.
EXTRACTOR_VERSION = "v0.5.0"


def fingerprint(
    *,
    prompt: str,
    system_prompt: Optional[str],
    history: list[dict[str, Any]],
    model_id: str,
    extractor_version: str,
) -> str:
    """SHA-256 of the canonical call context.

    Deterministic JSON-serialization (sort_keys, ensure_ascii) guarantees
    bit-stable fingerprints across runs and hosts.
    """
    payload = {
        "extractor_version": extractor_version,
        "model_id": model_id,
        "system_prompt": system_prompt or "",
        "prompt": prompt,
        "history": history or [],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def cached_completion(
    underlying: Callable[..., Awaitable[str]],
    *,
    cache_dir: Path,
    prompt: str,
    model_id: str,
    extractor_version: str = EXTRACTOR_VERSION,
    system_prompt: Optional[str] = None,
    history_messages: Optional[list[dict[str, Any]]] = None,
    **call_kwargs: Any,
) -> str:
    """Look up the LLM response in cache, call `underlying` on miss.

    `underlying` is an awaitable matching the openai-compatible LLM
    signature (prompt, system_prompt, history_messages, **kw).
    `call_kwargs` are forwarded verbatim — they are NOT included in the
    fingerprint so transient routing/timeout knobs do not bust the cache.
    Anything that semantically affects the answer must be in the
    fingerprint (prompt/system/history/model_id/extractor_version).
    """
    history = history_messages or []
    fp = fingerprint(
        prompt=prompt,
        system_prompt=system_prompt,
        history=history,
        model_id=model_id,
        extractor_version=extractor_version,
    )

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{fp}.json"

    if cache_path.is_file():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            response = payload.get("response")
            if isinstance(response, str):
                logger.debug("cache hit: %s", fp[:12])
                return response
            logger.warning(
                "cache file %s has non-string response — re-extracting",
                cache_path,
            )
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("cache file %s unreadable (%s) — re-extracting", cache_path, exc)

    response = await underlying(
        prompt,
        system_prompt=system_prompt,
        history_messages=history,
        **call_kwargs,
    )

    tmp = cache_path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(
                {
                    "fingerprint": fp,
                    "extractor_version": extractor_version,
                    "model_id": model_id,
                    "system_prompt": system_prompt or "",
                    "prompt": prompt,
                    "history": history,
                    "response": response,
                    "stored_at": time.time(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(cache_path)
    except OSError as exc:
        # Cache write failure is non-fatal — we still got a real response.
        logger.warning("cache write failed for %s: %s", cache_path, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

    return response


def clear_cache(cache_dir: Path) -> int:
    """Delete every cache file in `cache_dir`. Returns count removed.

    Manual eviction only — no TTL, no LRU. Call from a CLI or a test.
    """
    if not cache_dir.is_dir():
        return 0
    removed = 0
    for f in cache_dir.glob("*.json"):
        try:
            f.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("could not remove %s: %s", f, exc)
    return removed

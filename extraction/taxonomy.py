"""Hard enforcement of the declared entity-type vocabulary.

LightRAG's prompt asks the LLM to restrict `entity_type` to the list
injected via `addon_params`, but the constraint is soft: the LLM still
invents singleton types (`artifact`, `product`, `event`, `UNKNOWN`, …).
This module remaps any non-declared type to a fallback bucket so the
on-disk graph respects the taxonomy we committed to.
"""
from __future__ import annotations

from typing import Iterable


def normalize_entity_type(
    node: dict,
    allowed_types: Iterable[str],
    *,
    fallback: str = "concept",
) -> bool:
    """In-place: ensure `node['entity_type']` is in `allowed_types` (lowercased).

    Returns True if the type was remapped.
    """
    allowed = {t.lower() for t in allowed_types}
    raw = node.get("entity_type")
    current = (raw or "").strip().lower()
    if current in allowed:
        node["entity_type"] = current
        return False
    node["entity_type"] = fallback
    return True

"""Doc-kind → extraction-focus entity types.

Maps `doc_context` classifier tags (Phase 5.5b closed vocabulary) to a
short list of entity types the LLM should prioritize when extracting
from that doc. Nudges extraction on table-heavy / numeric-dense docs
(payslips, tax forms) where the LLM otherwise over-emphasizes generic
numeric entities and under-generates semantic types.

Pure data + one helper. Applied at ingest-time by core via the pack's
`extraction_hints` hook.
"""
from __future__ import annotations

from typing import Iterable


# Per-tag focus lists. Types must exist in the composed core+pack
# taxonomy; the hint is advisory (LLM may still extract other types).
# Keep each list short (≤10) so the prompt overhead stays bounded when
# a doc carries multiple tags.
_FOCUS_BY_TAG: dict[str, tuple[str, ...]] = {
    "work": (
        "employer", "role", "skill", "organization", "person", "amount", "date",
    ),
    "healthcare": (
        "medication", "diagnosis", "procedure", "medical_provider",
        "body_part", "person", "organization", "date",
    ),
    "finance": (
        "account", "amount", "organization", "person", "date",
    ),
    "property": (
        "property", "location", "amount", "person", "date",
    ),
    "vehicle": (
        "vehicle", "identifier", "amount", "person", "date",
    ),
    "identity": (
        "identifier", "person", "date", "location",
    ),
    "family": (
        "person", "event", "date",
    ),
    "legal": (
        "organization", "person", "location", "amount", "date", "document",
    ),
    "education": (
        "role", "skill", "organization", "date", "person",
    ),
    "travel": (
        "trip", "accommodation", "location", "date", "amount",
    ),
    "food": (
        "ingredient", "dish", "nutrient", "cooking_technique",
    ),
    "administrative": (
        "organization", "person", "date", "identifier",
    ),
    # `other` intentionally maps to no focus — fall back to the full
    # taxonomy, avoiding a bad nudge on unclassified docs.
}


_MAX_FOCUS_TYPES = 10


def focus_for_tags(tags: Iterable[str]) -> list[str]:
    """Union of focus types across `tags`, preserving first-seen order.

    Unknown tags contribute nothing. Returns an empty list when no tag
    maps to a non-empty focus (e.g. `other` or empty input) — caller
    should skip the EXTRACTION FOCUS prefix in that case.
    """
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags or ():
        for t in _FOCUS_BY_TAG.get(tag, ()):
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= _MAX_FOCUS_TYPES:
                return out
    return out


def extraction_hints(metadata: dict) -> list[str]:
    """Pack hook: return focus types based on `metadata.doc_context`."""
    tags = metadata.get("doc_context") or []
    return focus_for_tags(tags)

"""Temporal annotations on nodes and edges.

Post-processing pass that prefixes every node and edge description with
`[sourced: <dates>]` based on the source documents the fact was
extracted from (via `document_ids` → `metadata.json.document_date`).
The LLM then sees explicit temporal grounding in every retrieved
context chunk and can reason about which facts are most recent.

Domain-agnostic: applies to any graph regardless of content.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from extraction.provenance import parse_document_ids

SOURCED_PREFIX = "[sourced:"


def has_sourced_prefix(description: str | None) -> bool:
    return bool(description and description.startswith(SOURCED_PREFIX))


def build_sourced_prefix(dates: Iterable[date]) -> str:
    """`[sourced: YYYY-MM-DD, YYYY-MM-DD] ` (sorted ascending, dedup'd)."""
    unique_sorted = sorted(set(d for d in dates if d is not None))
    if not unique_sorted:
        return ""
    joined = ", ".join(d.isoformat() for d in unique_sorted)
    return f"{SOURCED_PREFIX} {joined}] "


def annotate_with_sourced_dates(
    record: dict,
    id_to_date: dict[str, date],
) -> bool:
    """In-place: prefix `record['description']` with a sourced-dates header.

    Idempotent (won't re-prefix if already annotated). Returns True iff
    the record was actually mutated.
    """
    desc = record.get("description") or ""
    if has_sourced_prefix(desc):
        return False

    doc_ids = parse_document_ids(record.get("document_ids"))
    dates = [id_to_date[d] for d in doc_ids if d in id_to_date]
    if not dates:
        return False

    prefix = build_sourced_prefix(dates)
    record["description"] = prefix + desc
    return True

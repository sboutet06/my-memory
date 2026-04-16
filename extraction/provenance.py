"""Post-processing: turn LightRAG's absolute `file_path` into portable `document_ids`.

LightRAG stamps `file_path` on every node and edge, concatenating paths
with `<SEP>` when an entity spans multiple source docs. That is a
leak of the local absolute path into the knowledge graph — bad for
portability (intent.md: "no lock-in, open formats"). This module
derives a stable, portable `document_ids` list from it.
"""
from __future__ import annotations

import re

# Multi-value delimiter used by LightRAG between merged source records.
SEP = "<SEP>"

# UUID v4 canonical form.
_UUID_RE = re.compile(
    r"(?:^|/)store/(?P<doc_id>[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})/"
)


def extract_document_ids(text: str | None) -> list[str]:
    """Parse any input text and return UUID doc-ids found under `store/…/`.

    Handles both LightRAG's SEP-joined `file_path` fields and free-form
    text (e.g. a query answer containing multiple `/store/{uuid}/…` refs).

    - Only UUIDv4 segments directly under `store/` qualify.
    - Order preserved; first occurrence wins on dedup.
    """
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _UUID_RE.finditer(text):
        doc_id = match.group("doc_id")
        if doc_id not in seen:
            seen.add(doc_id)
            out.append(doc_id)
    return out


def rewrite_node_provenance(node: dict) -> dict:
    """In-place: add `document_ids` derived from `file_path`. Idempotent.

    Stored as a `<SEP>`-joined string (matches LightRAG's convention for
    multi-value fields like `source_id` and `file_path`), since GraphML
    only supports scalar attribute values. Use `parse_document_ids()` to
    get a list back.
    """
    ids = extract_document_ids(node.get("file_path"))
    node["document_ids"] = SEP.join(ids)
    return node


def parse_document_ids(field_value: str | None) -> list[str]:
    """Read-side: split a stored `document_ids` field back into a list."""
    if not field_value:
        return []
    return [part for part in field_value.split(SEP) if part]

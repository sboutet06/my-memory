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


def extract_document_ids(file_path: str | None) -> list[str]:
    """Parse one-or-more absolute paths separated by `<SEP>` into doc-ids.

    - Only UUIDv4 path segments under `/store/` qualify.
    - Order preserved; first occurrence wins on dedup.
    - Any non-conforming input yields an empty list (silent on noise).
    """
    if not file_path:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for part in file_path.split(SEP):
        match = _UUID_RE.search(part)
        if not match:
            continue
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

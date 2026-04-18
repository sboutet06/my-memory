"""Answer-shaped index nodes — retrieval-native synthetic graph structure.

Phase 5.1's diagnostics showed the KG is good at surfacing relevant
entities but weak at aggregating the DOCUMENTS behind them. Answer-
shaped queries ("who", "what X has Y", "list all Z") want a single node
that enumerates the docs satisfying the predicate.

Two generic index-node kinds, both derived from the graph without any
domain-specific rule:

  Profile: <entity_name>    one per named entity appearing in ≥N docs.
                            Description: enumerates the docs, includes
                            `/store/<uuid>/` paths so the LLM can cite.
  Catalog: <entity_type>    one per entity type with ≥M entities across
                            ≥N docs. Description: entity list + doc
                            paths grouped by member.

Generation is corpus-agnostic; the thresholds are the only tuning knob.
No filenames, no entity names, no query phrases mentioned in the code.
Adding a domain (healthcare, legal, research) needs no change here.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from extraction.provenance import parse_document_ids

ENTITY_PROFILE_PREFIX = "Profile: "
CATALOG_PREFIX = "Catalog: "

ENTITY_PROFILE_TYPE = "entity_profile"
CATALOG_TYPE = "catalog_index"

# Entity types that are too noisy to profile / catalog. Same philosophy
# as retrieval_enhance._LOW_SIGNAL_TYPES — numeric/identifier types and
# pack-infra types don't carry retrieval intent for human queries.
_LOW_SIGNAL_TYPES: frozenset[str] = frozenset({
    "amount", "date", "identifier",
    "transaction", "transaction_category", "account",
    ENTITY_PROFILE_TYPE, CATALOG_TYPE,
})

DEFAULT_MIN_DOCS_FOR_PROFILE = 2
DEFAULT_MIN_ENTITIES_FOR_CATALOG = 2

_MAX_DOC_LINES_PER_NODE = 20
_MAX_ENTITIES_PER_CATALOG_LINE = 8


def _store_path(doc_id: str) -> str:
    return f"/store/{doc_id}/content.md"


def _doc_line(doc_id: str, store_meta: dict) -> str:
    meta = store_meta.get(doc_id) or {}
    fn = meta.get("original_filename", "")
    date = meta.get("document_date", "")
    ctx = meta.get("doc_context") or []
    suffix_bits = []
    if fn:
        suffix_bits.append(fn)
    if date:
        suffix_bits.append(f"date={date}")
    if ctx:
        suffix_bits.append(f"context={'/'.join(ctx)}")
    suffix = f" ({', '.join(suffix_bits)})" if suffix_bits else ""
    return f"  - {_store_path(doc_id)}{suffix}"


def _aggregate_contexts(doc_ids: Iterable[str], store_meta: dict) -> list[str]:
    """Union of doc_context tags across the given docs, in first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for doc_id in doc_ids:
        meta = store_meta.get(doc_id) or {}
        for tag in (meta.get("doc_context") or []):
            if tag not in seen:
                seen.add(tag)
                out.append(tag)
    return out


def _entity_doc_ids(node: dict) -> list[str]:
    raw = node.get("document_ids")
    if isinstance(raw, list):
        return [d for d in raw if d]
    return parse_document_ids(raw)


# --------------------------- EntityProfile ------------------------------


def _plan_entity_profiles(
    graph: dict[str, dict],
    store_meta: dict,
    min_docs: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, node in graph.items():
        etype = node.get("entity_type") or ""
        if etype in _LOW_SIGNAL_TYPES:
            continue
        doc_ids = [d for d in _entity_doc_ids(node) if d in store_meta]
        if len(doc_ids) < min_docs:
            continue
        # Build a stable description: name, type, list of docs (each
        # with its own per-doc context). No aggregated "primary context"
        # header — that narrows the embedding toward one context and
        # under-retrieves cross-context queries (measured).
        lines = [
            f"Profile of {name} (type: {etype}).",
            f"Appears in {len(doc_ids)} documents:",
        ]
        for doc_id in sorted(doc_ids)[:_MAX_DOC_LINES_PER_NODE]:
            lines.append(_doc_line(doc_id, store_meta))
        if len(doc_ids) > _MAX_DOC_LINES_PER_NODE:
            lines.append(f"  …and {len(doc_ids) - _MAX_DOC_LINES_PER_NODE} more.")
        out.append({
            "name": f"{ENTITY_PROFILE_PREFIX}{name}",
            "entity_type": ENTITY_PROFILE_TYPE,
            "description": "\n".join(lines),
            "source_id": doc_ids[0],
            "file_path": _store_path(doc_ids[0]),
            "document_ids": doc_ids,
        })
    return out


# ------------------------------ Catalog ---------------------------------


def _plan_catalogs(
    graph: dict[str, dict],
    store_meta: dict,
    min_entities: int,
) -> list[dict[str, Any]]:
    # Group entities by type, collecting their member names + doc_ids.
    type_members: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    for name, node in graph.items():
        etype = node.get("entity_type") or ""
        if etype in _LOW_SIGNAL_TYPES:
            continue
        doc_ids = [d for d in _entity_doc_ids(node) if d in store_meta]
        if not doc_ids:
            continue
        type_members[etype].append((name, doc_ids))

    out: list[dict[str, Any]] = []
    for etype, members in sorted(type_members.items()):
        if len(members) < min_entities:
            continue
        all_docs: set[str] = set()
        for _, dids in members:
            all_docs.update(dids)
        if len(all_docs) < min_entities:
            # Require the members to span at least `min_entities` documents,
            # otherwise the catalog collapses to a single-doc index.
            continue

        lines = [
            f"Catalog of {etype} entities across the corpus.",
            f"{len(members)} entities found across {len(all_docs)} documents:",
        ]
        for name, dids in sorted(members):
            short_docs = sorted(dids)[:_MAX_ENTITIES_PER_CATALOG_LINE]
            path_bits = ", ".join(_store_path(d) for d in short_docs)
            lines.append(f"  - {name} [{path_bits}]")
        out.append({
            "name": f"{CATALOG_PREFIX}{etype}",
            "entity_type": CATALOG_TYPE,
            "description": "\n".join(lines),
            "source_id": sorted(all_docs)[0],
            "file_path": _store_path(sorted(all_docs)[0]),
            "document_ids": sorted(all_docs),
        })
    return out


# ------------------------------ public ----------------------------------


def plan_index_nodes(
    graph: dict[str, dict],
    store_meta: dict,
    *,
    min_docs_for_profile: int = DEFAULT_MIN_DOCS_FOR_PROFILE,
    min_entities_for_catalog: int = DEFAULT_MIN_ENTITIES_FOR_CATALOG,
) -> list[dict[str, Any]]:
    """Plan synthetic Profile / Catalog nodes. Pure function, no I/O."""
    profiles = _plan_entity_profiles(graph, store_meta, min_docs_for_profile)
    catalogs = _plan_catalogs(graph, store_meta, min_entities_for_catalog)
    # Deterministic order: profiles alphabetical, catalogs alphabetical.
    profiles.sort(key=lambda n: n["name"])
    catalogs.sort(key=lambda n: n["name"])
    return profiles + catalogs


def is_index_node_name(name: str) -> bool:
    return name.startswith(ENTITY_PROFILE_PREFIX) or name.startswith(CATALOG_PREFIX)

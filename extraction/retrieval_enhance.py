"""Add per-document summary chunks to the chunk index.

Addresses the chunks_vdb bottleneck surfaced by Phase 5.1 diagnostics:
queries that match a document via entities often fail to retrieve any
of that doc's chunks because the chunks' local text doesn't match the
query tokens. A compact per-doc summary — filename, date, top entity
names, pack-produced highlights — gives chunks_vdb a retrieval-friendly
anchor for every document.

Generic by design:
  - Every store doc gets a summary chunk.
  - Pack extras are pulled via each pack's optional
    `summary_extras_for_doc(rag, doc_id)` async hook — core never
    inspects pack schemas.
  - Low-signal entity types (numerics, identifiers, pack-declared infra)
    are filtered out of the Key entities list.
  - No query-time cost; summaries are upserted once, post-extraction.
  - Idempotent: re-running upserts the same keys.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

from extraction.provenance import parse_document_ids

from extraction.index_nodes import (
    CATALOG_PREFIX,
    ENTITY_PROFILE_PREFIX,
    is_index_node_name,
    plan_index_nodes,
)

logger = logging.getLogger(__name__)

SUMMARY_CHUNK_PREFIX = "summary-chunk-"
_SUMMARY_CONTENT_HEAD_CHARS = 1500
_SUMMARY_MAX_ENTITIES = 40

# Core types that never belong in the Key entities line. Packs extend
# this via `low_signal_types`; union happens at call sites.
_CORE_LOW_SIGNAL_TYPES: frozenset[str] = frozenset({
    "amount", "date", "identifier",
})


def _pack_low_signal_types(packs: Iterable[Any]) -> frozenset[str]:
    extra: set[str] = set()
    for p in packs or ():
        extra.update(getattr(p, "low_signal_types", ()) or ())
    return frozenset(extra)


def _fmt_date(raw) -> str:
    return str(raw) if raw else "unknown"


def _clean_content_head(content: str) -> str:
    """Keep natural-language lines, drop table noise and section separators.

    Heuristic: skip lines that are >50% `|` / whitespace / dashes (markdown
    table row / separator) — these swamp the retrieval signal with tokens
    the embedder can't latch onto.
    """
    out: list[str] = []
    taken = 0
    for raw in (content or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        noise_chars = sum(1 for c in s if c in "|-: ")
        if noise_chars / max(len(s), 1) > 0.5:
            continue
        remaining = _SUMMARY_CONTENT_HEAD_CHARS - taken
        if remaining <= 0:
            break
        if len(s) > remaining:
            s = s[:remaining]
        out.append(s)
        taken += len(s) + 1
    return "\n".join(out)


def build_doc_summary(
    metadata: dict[str, Any],
    content_md: str,
    entity_names: list[str],
    structured_extras: Optional[list[str]] = None,
) -> str:
    """Compose a retrieval-friendly summary for one document.

    Kept deliberately compact — no body-content head — so these summary
    chunks complement the existing Docling content chunks rather than
    competing with them in chunks_vdb top-K.
    """
    del content_md
    lines: list[str] = []
    fn = metadata.get("original_filename") or "unknown"
    date = _fmt_date(metadata.get("document_date"))
    doc_id = metadata.get("document_id") or ""
    quality = metadata.get("extraction_quality") or "unknown"
    doc_context = metadata.get("doc_context") or []
    lines.append(f"Document: {fn}")
    lines.append(f"Filename tokens: {fn.replace('_', ' ').replace('-', ' ')}")
    lines.append(f"Document date: {date}")
    lines.append(f"Document ID: {doc_id}")
    lines.append(f"Extraction quality: {quality}")
    if doc_context:
        lines.append(f"Document context: {', '.join(doc_context)}")
    if entity_names:
        short = entity_names[:_SUMMARY_MAX_ENTITIES]
        lines.append("Key entities: " + ", ".join(short))
    if structured_extras:
        lines.append("Structured highlights:")
        for item in structured_extras:
            lines.append(f"  - {item}")
    return "\n".join(lines)


# --------------------------- writer (async) -----------------------------


async def _entity_names_for_doc(
    rag, doc_id: str, low_signal_types: frozenset[str],
) -> list[str]:
    """Return semantic-signal entity names for `doc_id`.

    Filters out low-signal types (core numerics + pack-declared infra)
    so the summary surfaces people, organizations, locations, roles,
    medications, vehicles — the tokens a natural-language query is
    likely to contain.
    """
    kg = rag.chunk_entity_relation_graph
    labels = await kg.get_all_labels()
    names: list[str] = []
    for name in labels:
        node = await kg.get_node(name)
        if node is None:
            continue
        ids = parse_document_ids(node.get("document_ids"))
        if doc_id not in ids:
            continue
        if (node.get("entity_type") or "") in low_signal_types:
            continue
        names.append(name)
    return names


async def _pack_extras_for_doc(packs: Iterable[Any], rag, doc_id: str) -> list[str]:
    """Collect extras lines from every pack that exposes `summary_extras_for_doc`."""
    out: list[str] = []
    for pack in packs or ():
        hook = getattr(pack, "summary_extras_for_doc", None)
        if not callable(hook):
            continue
        try:
            lines = await hook(rag, doc_id)
        except Exception as exc:
            logger.warning("pack %r summary_extras failed for %s: %s",
                           getattr(pack, "name", "?"), doc_id, exc)
            continue
        if lines:
            out.extend(lines)
    return out


async def write_doc_summary_chunks(
    rag,
    store_root: Path,
    *,
    packs: Iterable[Any] = (),
) -> dict:
    """Upsert one summary chunk per document under `store_root`.

    `packs` provides optional `summary_extras_for_doc` hooks and
    `low_signal_types` attributes. Empty/missing = core-only behavior.

    Returns {docs_scanned, summaries_written}.
    """
    if not store_root.exists():
        return {"docs_scanned": 0, "summaries_written": 0}

    packs_list = list(packs) if packs else []
    low_signal = _CORE_LOW_SIGNAL_TYPES | _pack_low_signal_types(packs_list)

    summaries: dict[str, dict] = {}
    scanned = 0
    for entry in sorted(store_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".tmp-"):
            continue
        meta_path = entry / "metadata.json"
        md_path = entry / "content.md"
        if not (meta_path.is_file() and md_path.is_file()):
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        content = md_path.read_text(encoding="utf-8")
        doc_id = meta.get("document_id")
        if not doc_id:
            continue

        entity_names = await _entity_names_for_doc(rag, doc_id, low_signal)
        extras = await _pack_extras_for_doc(packs_list, rag, doc_id)
        summary = build_doc_summary(meta, content, entity_names, extras)

        chunk_id = f"{SUMMARY_CHUNK_PREFIX}{doc_id}"
        summaries[chunk_id] = {
            "content": summary,
            "full_doc_id": doc_id,
            "file_path": f"/store/{doc_id}/content.md",
        }
        scanned += 1

    if summaries:
        await rag.chunks_vdb.upsert(summaries)
        await rag.chunks_vdb.index_done_callback()
        # Also mirror into the KV chunk store so downstream retrieval
        # lookups via full_doc_id remain consistent.
        await rag.text_chunks.upsert(summaries)
        await rag.text_chunks.index_done_callback()

    logger.info(
        "Wrote %d summary chunks across %d docs", len(summaries), scanned,
    )
    return {"docs_scanned": scanned, "summaries_written": len(summaries)}


# --------------------- Phase 5.4: answer-shaped indexes -----------------


def _build_store_meta(store_root: Path) -> dict:
    """{doc_id: metadata_dict} for every doc in the store."""
    out: dict[str, dict] = {}
    if not store_root.exists():
        return out
    for entry in sorted(store_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".tmp-"):
            continue
        meta_path = entry / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        doc_id = meta.get("document_id")
        if doc_id:
            out[doc_id] = meta
    return out


async def _cleanup_prior_index_nodes(rag) -> int:
    """Delete any existing Profile:/Catalog: nodes; idempotency for re-runs."""
    kg = rag.chunk_entity_relation_graph
    labels = await kg.get_all_labels()
    stale = [n for n in labels if is_index_node_name(n)]
    for name in stale:
        try:
            await rag.adelete_by_entity(name)
        except Exception as exc:
            logger.warning("failed to delete %r: %s", name, exc)
    return len(stale)


async def write_index_nodes(
    rag,
    store_root: Path,
    *,
    min_docs_for_profile: int = 2,
    min_entities_for_catalog: int = 2,
    dry_run: bool = False,
    packs: Iterable[Any] = (),
) -> dict:
    """Plan + inject answer-shaped index nodes (Profile / Catalog).

    `packs` contributes optional `low_signal_types` that extend the core
    set hidden from Profile/Catalog indexing.
    """
    from extraction.graph import snapshot_nodes  # local to avoid cycles

    store_meta = _build_store_meta(store_root)
    if not store_meta:
        return {"nodes_planned": 0, "nodes_written": 0, "stale_removed": 0,
                "dry_run": dry_run}

    snapshot = await snapshot_nodes(rag)
    # Exclude prior index nodes from the planner's view so its filters
    # don't compound on previous runs.
    live_snapshot = {k: v for k, v in snapshot.items() if not is_index_node_name(k)}

    extra_low_signal = _pack_low_signal_types(packs or ())

    plan = plan_index_nodes(
        live_snapshot, store_meta,
        min_docs_for_profile=min_docs_for_profile,
        min_entities_for_catalog=min_entities_for_catalog,
        extra_low_signal_types=extra_low_signal,
    )

    if dry_run:
        return {
            "nodes_planned": len(plan),
            "nodes_written": 0,
            "stale_removed": 0,
            "dry_run": True,
            "profiles": [n["name"] for n in plan if n["name"].startswith(ENTITY_PROFILE_PREFIX)],
            "catalogs": [n["name"] for n in plan if n["name"].startswith(CATALOG_PREFIX)],
        }

    stale = await _cleanup_prior_index_nodes(rag)

    written = 0
    errors: list[str] = []
    for spec in plan:
        name = spec["name"]
        payload = {
            "entity_type": spec["entity_type"],
            "description": spec["description"],
            "source_id": spec["source_id"],
            "file_path": spec["file_path"],
        }
        try:
            await rag.acreate_entity(name, payload)
            written += 1
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    await rag.chunk_entity_relation_graph.index_done_callback()

    return {
        "nodes_planned": len(plan),
        "nodes_written": written,
        "stale_removed": stale,
        "errors": errors[:10],
        "dry_run": False,
    }

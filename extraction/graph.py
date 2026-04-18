"""LightRAG wrapper: build a rag instance, extract from store docs, post-process.

Provenance post-processing rewrites `file_path` (absolute local paths)
into a portable `document_ids` list on every node and edge.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

from lightrag import LightRAG

import numpy as np

from extraction.alias import (
    DEFAULT_CLUSTERABLE_TYPES,
    DEFAULT_THRESHOLD,
    cluster_entities,
    pick_canonical,
)
from datetime import date

from extraction.config import ExtractionConfig
from extraction.llm import make_embedding_func, make_llm_func
from extraction.provenance import rewrite_node_provenance
from extraction.rerank import rerank_func
from extraction.taxonomy import normalize_entity_type
from extraction.temporal import annotate_with_sourced_dates

logger = logging.getLogger(__name__)

DEFAULT_WORKING_DIR = Path("extraction_store")


async def build_rag(
    working_dir: Path = DEFAULT_WORKING_DIR,
    config: ExtractionConfig | None = None,
) -> LightRAG:
    """Instantiate LightRAG with the project's LLM, embeddings, and taxonomy."""
    config = config or ExtractionConfig.from_env()
    working_dir.mkdir(parents=True, exist_ok=True)
    rag = LightRAG(
        working_dir=str(working_dir),
        llm_model_func=make_llm_func(config),
        embedding_func=make_embedding_func(config),
        rerank_model_func=rerank_func,
        addon_params=config.addon_params(),
    )
    await rag.initialize_storages()
    return rag


def discover_store_docs(store_root: Path) -> list[tuple[Path, dict]]:
    """Return (content_md_path, metadata_dict) for every doc in `store_root`."""
    out: list[tuple[Path, dict]] = []
    if not store_root.exists():
        return out
    for entry in sorted(store_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".tmp-"):
            continue
        meta_path = entry / "metadata.json"
        md_path = entry / "content.md"
        if not (meta_path.is_file() and md_path.is_file()):
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        out.append((md_path, meta))
    return out


def _prepend_date_header(text: str, document_date: str | None) -> str:
    """Prefix the content with a `[DOCUMENT DATE: YYYY-MM-DD]` line when known.

    The LLM then sees an explicit temporal anchor on every chunk and can
    attach it to the facts it extracts. Skipped when the date is unknown.
    """
    if not document_date:
        return text
    return f"[DOCUMENT DATE: {document_date}]\n\n{text}"


def _prepend_extraction_focus(text: str, focus_types: list[str]) -> str:
    """Prefix `[EXTRACTION FOCUS: ...]` when packs return hints for this doc.

    Biases the LLM toward the listed entity types on table-heavy /
    numeric-dense docs (payslips, tax forms). No-op when the list is
    empty — falls back to the full taxonomy.
    """
    if not focus_types:
        return text
    joined = ", ".join(focus_types)
    return (
        f"[EXTRACTION FOCUS: prioritize entities of these types: {joined}.]\n\n"
        f"{text}"
    )


def _resolve_extraction_hints(packs: Iterable[object], metadata: dict) -> list[str]:
    """Union focus types from each pack's `extraction_hints(metadata)` hook.

    Packs without the hook contribute nothing; ordering is first-seen
    across registration order. Duplicates dropped.
    """
    out: list[str] = []
    seen: set[str] = set()
    for pack in packs or ():
        hook = getattr(pack, "extraction_hints", None)
        if not callable(hook):
            continue
        try:
            hints = hook(metadata) or []
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("pack %r extraction_hints failed: %s",
                           getattr(pack, "name", "?"), exc)
            continue
        for t in hints:
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
    return out


async def extract_documents(
    rag: LightRAG,
    docs: Iterable[tuple[Path, dict]],
    *,
    corrections_root: Path | None = None,
    packs: Iterable[object] = (),
) -> int:
    """Insert the given docs into `rag`. Returns count inserted.

    Resolves each doc path to an absolute string so downstream
    provenance parsing sees a canonical `/store/{doc_id}/` segment, and
    prepends a document-date header when the ingestion metadata carries
    one.

    When `corrections_root` is given, source corrections are consulted
    per-doc to apply `content_md_override_path` + `content_replacements`
    before extraction — giving alternate-OCR output priority over the
    raw Docling markdown.
    """
    from corrections.io import load_source_correction
    from corrections.overlay import apply_metadata_overlay, resolve_content

    packs_list = list(packs) if packs else []

    texts: list[str] = []
    ids: list[str] = []
    file_paths: list[str] = []
    overlay_hits = 0
    focus_hits = 0
    for md_path, meta in docs:
        raw = md_path.read_text(encoding="utf-8")
        correction = None
        if corrections_root is not None:
            correction = load_source_correction(corrections_root, meta["document_id"])
            meta = apply_metadata_overlay(meta, correction)
            effective = resolve_content(raw, correction, corrections_root)
            if correction is not None and correction.overrides.get("content_md_override_path"):
                overlay_hits += 1
        else:
            effective = raw

        body = _prepend_date_header(effective, meta.get("document_date"))
        focus_types = _resolve_extraction_hints(packs_list, meta)
        if focus_types:
            focus_hits += 1
        body = _prepend_extraction_focus(body, focus_types)

        texts.append(body)
        ids.append(meta["document_id"])
        file_paths.append(str(md_path.resolve()))
    if not texts:
        return 0
    if overlay_hits:
        logger.info("Applied content overlay on %d/%d docs", overlay_hits, len(texts))
    if focus_hits:
        logger.info("Applied extraction focus hints on %d/%d docs", focus_hits, len(texts))
    logger.info("Extracting from %d document(s)", len(texts))
    await rag.ainsert(texts, ids=ids, file_paths=file_paths)
    return len(texts)


async def post_process(
    rag: LightRAG,
    allowed_entity_types: Iterable[str],
    type_fallback: str = "concept",
) -> dict:
    """Rewrite `file_path` → `document_ids` and enforce the type vocabulary.

    - Nodes: add `document_ids`, remap unknown `entity_type` to `fallback`.
    - Edges: add `document_ids`.

    Returns a small stats dict for observability.
    """
    kg = rag.chunk_entity_relation_graph
    labels = await kg.get_all_labels()
    allowed = list(allowed_entity_types)

    node_count = 0
    edge_count = 0
    types_remapped = 0
    edges_seen: set[tuple[str, str]] = set()

    for name in labels:
        node = await kg.get_node(name)
        if node is None:
            continue
        rewrite_node_provenance(node)
        if normalize_entity_type(node, allowed, fallback=type_fallback):
            types_remapped += 1
        await kg.upsert_node(name, node)
        node_count += 1

        for src, tgt in (await kg.get_node_edges(name) or []):
            key = tuple(sorted([src, tgt]))
            if key in edges_seen:
                continue
            edges_seen.add(key)
            edge = await kg.get_edge(src, tgt)
            if edge is None:
                continue
            rewrite_node_provenance(edge)
            await kg.upsert_edge(src, tgt, edge)
            edge_count += 1

    # The networkx graph storage persists via `index_done_callback`,
    # not via `finalize()` (which is a no-op). Force a flush here so our
    # upserts land on disk.
    await kg.index_done_callback()

    return {
        "nodes_rewritten": node_count,
        "edges_rewritten": edge_count,
        "entity_types_remapped": types_remapped,
    }


def _build_doc_id_to_date(store_root: Path) -> dict[str, date]:
    """Read `store/*/metadata.json` → {document_id: date}. None dates skipped."""
    mapping: dict[str, date] = {}
    if not store_root.exists():
        return mapping
    for entry in sorted(store_root.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        doc_id = meta.get("document_id")
        raw_date = meta.get("document_date")
        if not doc_id or not raw_date:
            continue
        try:
            mapping[doc_id] = date.fromisoformat(raw_date)
        except ValueError:
            continue
    return mapping


async def annotate_temporal(
    rag: LightRAG,
    store_root: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Prefix every node and edge description with `[sourced: dates]`.

    Pure post-processing. Idempotent: re-running skips already-annotated
    records. Returns counts.
    """
    id_to_date = _build_doc_id_to_date(store_root)
    if not id_to_date:
        return {"nodes_annotated": 0, "edges_annotated": 0, "dry_run": dry_run}

    kg = rag.chunk_entity_relation_graph
    labels = await kg.get_all_labels()

    nodes_annotated = 0
    edges_annotated = 0
    edges_seen: set[tuple[str, str]] = set()

    for name in labels:
        node = await kg.get_node(name)
        if node is None:
            continue
        if annotate_with_sourced_dates(node, id_to_date):
            nodes_annotated += 1
            if not dry_run:
                await kg.upsert_node(name, node)

        for src, tgt in (await kg.get_node_edges(name) or []):
            key = tuple(sorted([src, tgt]))
            if key in edges_seen:
                continue
            edges_seen.add(key)
            edge = await kg.get_edge(src, tgt)
            if edge is None:
                continue
            if annotate_with_sourced_dates(edge, id_to_date):
                edges_annotated += 1
                if not dry_run:
                    await kg.upsert_edge(src, tgt, edge)

    if not dry_run and (nodes_annotated or edges_annotated):
        await kg.index_done_callback()

    return {
        "nodes_annotated": nodes_annotated,
        "edges_annotated": edges_annotated,
        "dry_run": dry_run,
    }


async def resolve_aliases(
    rag: LightRAG,
    config: ExtractionConfig,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    clusterable_types: Iterable[str] = DEFAULT_CLUSTERABLE_TYPES,
    dry_run: bool = True,
) -> dict:
    """Cluster entities by name-embedding similarity and merge non-singletons.

    Progressive + domain-agnostic: operates on whatever entities the graph
    contains. Merges use LightRAG's native `amerge_entities`, which
    re-points edges and unions provenance/source fields.
    """
    kg = rag.chunk_entity_relation_graph
    labels = await kg.get_all_labels()
    if not labels:
        return {"entities": 0, "clusters": 0, "merged": 0, "plan": []}

    types: list[str] = []
    names: list[str] = []
    for label in labels:
        node = await kg.get_node(label)
        if node is None:
            continue
        names.append(label)
        types.append(node.get("entity_type") or "")

    # Reuse the extraction embedding model — names are short, one batch.
    embedding_func = make_embedding_func(config).func
    raw = await embedding_func(names)
    embeddings = np.asarray(raw, dtype=np.float32)
    # `make_embedding_func` already requests `normalize_embeddings=True`,
    # so `A @ A.T` is cosine similarity.

    ambiguous_groups: list[list[str]] = []
    clusters = cluster_entities(
        names, embeddings, types,
        threshold=threshold,
        clusterable_types=clusterable_types,
        ambiguous_out=ambiguous_groups,
    )

    plan: list[dict] = []
    merged = 0
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        canonical = pick_canonical(cluster)
        sources = [n for n in cluster if n != canonical]
        plan.append({"canonical": canonical, "merged_from": sources})
        if not dry_run:
            try:
                await rag.amerge_entities(
                    source_entities=sources,
                    target_entity=canonical,
                    merge_strategy={
                        "description": "concatenate",
                        "entity_type": "keep_first",
                        "source_id": "join_unique",
                        "file_path": "join_unique",
                        "document_ids": "join_unique",
                    },
                )
                merged += len(sources)
            except Exception as exc:
                logger.warning("merge failed: %s → %s: %s", sources, canonical, exc)

    return {
        "entities": len(names),
        "clusters": len([c for c in clusters if len(c) > 1]),
        "merged": merged,
        "dry_run": dry_run,
        "plan": plan,
        "ambiguous_groups": ambiguous_groups,
    }


async def apply_derivation_plan(rag: LightRAG, plan) -> dict:
    """Execute a derivation Plan against the persisted graph.

    `plan` is a `corrections.derivation_applier.Plan`. Kept untyped here
    so `extraction.graph` doesn't import from `corrections`.

    Order:
      1. Entity-type rewrites — node `entity_type` reassigned in place.
      2. Merge ops — run via LightRAG's `amerge_entities`, which
         re-points edges and unions provenance/source fields.

    Idempotent: a TypeChange whose new_type already matches the stored
    node is a no-op; a MergeOp whose `sources` are already absent (prior
    run merged them) is a no-op.
    """
    kg = rag.chunk_entity_relation_graph

    types_applied = 0
    types_skipped = 0
    for change in plan.type_changes:
        node = await kg.get_node(change.name)
        if node is None:
            types_skipped += 1
            continue
        if (node.get("entity_type") or "") == change.new_type:
            types_skipped += 1
            continue
        node["entity_type"] = change.new_type
        await kg.upsert_node(change.name, node)
        types_applied += 1

    merges_applied = 0
    merges_skipped = 0
    merge_errors: list[str] = []
    for op in plan.merge_ops:
        # Drop sources already absent (idempotency on re-run).
        live_sources = []
        for s in op.sources:
            if await kg.get_node(s) is not None:
                live_sources.append(s)
        if not live_sources:
            merges_skipped += 1
            continue
        if await kg.get_node(op.canonical) is None:
            merges_errors_append = f"canonical {op.canonical!r} missing; skipping merge"
            merge_errors.append(merges_errors_append)
            continue
        try:
            await rag.amerge_entities(
                source_entities=live_sources,
                target_entity=op.canonical,
                merge_strategy={
                    "description": "concatenate",
                    "entity_type": "keep_first",
                    "source_id": "join_unique",
                    "file_path": "join_unique",
                    "document_ids": "join_unique",
                },
            )
            merges_applied += 1
        except Exception as exc:
            merge_errors.append(f"merge {op.canonical} ← {live_sources}: {exc}")

    if types_applied or merges_applied:
        await kg.index_done_callback()

    return {
        "types_applied": types_applied,
        "types_skipped": types_skipped,
        "merges_applied": merges_applied,
        "merges_skipped": merges_skipped,
        "merge_errors": merge_errors,
    }


async def snapshot_nodes(rag: LightRAG) -> dict[str, dict]:
    """Return `{name: node_dict}` for every entity in the graph.

    Used by downstream (e.g. corrections emitters) to reason about the
    current state without pulling in LightRAG's storage objects.
    """
    kg = rag.chunk_entity_relation_graph
    labels = await kg.get_all_labels()
    out: dict[str, dict] = {}
    for name in labels:
        node = await kg.get_node(name)
        if node is not None:
            out[name] = dict(node)
    return out


async def graph_stats(rag: LightRAG) -> dict:
    """Compact descriptive stats about the extracted graph."""
    kg = rag.chunk_entity_relation_graph
    labels = await kg.get_all_labels()
    type_hist: dict[str, int] = {}
    degrees: list[int] = []
    for name in labels:
        node = await kg.get_node(name)
        if node is None:
            continue
        t = node.get("entity_type") or "null"
        type_hist[t] = type_hist.get(t, 0) + 1
        edges = await kg.get_node_edges(name) or []
        degrees.append(len(edges))
    isolated = sum(1 for d in degrees if d == 0)
    return {
        "entity_count": len(labels),
        "with_edges": len(labels) - isolated,
        "isolated": isolated,
        "type_histogram": dict(sorted(type_hist.items(), key=lambda kv: -kv[1])),
    }

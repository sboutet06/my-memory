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

from extraction.config import ExtractionConfig
from extraction.llm import make_embedding_func, make_llm_func
from extraction.provenance import rewrite_node_provenance
from extraction.taxonomy import normalize_entity_type

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


async def extract_documents(
    rag: LightRAG,
    docs: Iterable[tuple[Path, dict]],
) -> int:
    """Insert the given docs into `rag`. Returns count inserted.

    Resolves each doc path to an absolute string so downstream
    provenance parsing sees a canonical `/store/{doc_id}/` segment, and
    prepends a document-date header when the ingestion metadata carries
    one.
    """
    texts: list[str] = []
    ids: list[str] = []
    file_paths: list[str] = []
    for md_path, meta in docs:
        raw = md_path.read_text(encoding="utf-8")
        texts.append(_prepend_date_header(raw, meta.get("document_date")))
        ids.append(meta["document_id"])
        file_paths.append(str(md_path.resolve()))
    if not texts:
        return 0
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

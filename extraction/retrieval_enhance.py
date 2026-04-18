"""Add per-document summary chunks to the chunk index.

Addresses the chunks_vdb bottleneck surfaced by Phase 5.1 diagnostics:
queries that match a document via entities often fail to retrieve any
of that doc's chunks because the chunks' local text doesn't match the
query tokens. A compact per-doc summary — filename, date, top entity
names, pack highlights, content head — gives chunks_vdb a retrieval-
friendly anchor for every document.

Generic by design:
  - Every store doc gets a summary chunk.
  - The summary composer accepts optional `structured_extras` produced
    by pack extractors (e.g. bank-statement category totals), so pack
    signals flow into retrieval without the enhancer knowing about
    individual pack schemas.
  - No query-time cost; summaries are upserted once, post-extraction.
  - Idempotent: re-running upserts the same keys.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from extraction.provenance import parse_document_ids

logger = logging.getLogger(__name__)

SUMMARY_CHUNK_PREFIX = "summary-chunk-"
_SUMMARY_CONTENT_HEAD_CHARS = 1500
_SUMMARY_MAX_ENTITIES = 40

# Entity types that carry semantic retrieval signal. Numeric/identifier types
# pollute the summary and crowd out names — drop them from the summary view.
_LOW_SIGNAL_TYPES: frozenset[str] = frozenset({
    "amount", "date", "identifier",
    # Pack-injected infra — summary-level relevance is already covered by
    # the structured_extras block.
    "transaction", "transaction_category", "account",
})


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
        # Cap each line so a single very long line can't blow the budget.
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
    # Note: `content_md` is intentionally unused for body text. See docstring.
    del content_md
    lines: list[str] = []
    fn = metadata.get("original_filename") or "unknown"
    date = _fmt_date(metadata.get("document_date"))
    doc_id = metadata.get("document_id") or ""
    quality = metadata.get("extraction_quality") or "unknown"
    lines.append(f"Document: {fn}")
    # Repeat filename tokens unquoted so they embed as plain words too.
    lines.append(f"Filename tokens: {fn.replace('_', ' ').replace('-', ' ')}")
    lines.append(f"Document date: {date}")
    lines.append(f"Document ID: {doc_id}")
    lines.append(f"Extraction quality: {quality}")
    if entity_names:
        short = entity_names[:_SUMMARY_MAX_ENTITIES]
        lines.append("Key entities: " + ", ".join(short))
    if structured_extras:
        lines.append("Structured highlights:")
        for item in structured_extras:
            lines.append(f"  - {item}")
    return "\n".join(lines)


# --------------------- structured-extras composers -----------------------


def transactions_extras(rag_node_attrs_list: list[dict]) -> list[str]:
    """One line per (direction, category) summary, sorted by amount desc."""
    out: list[tuple[str, str]] = []
    for attrs in rag_node_attrs_list:
        cat = attrs.get("category", "")
        direction = attrs.get("direction", "")
        total = attrs.get("total_amount", "")
        count = attrs.get("count", "")
        out.append((
            total,
            f"Category {cat} ({direction}): {total} EUR across {count} transactions",
        ))
    # Sort descending by total (string compare is OK for our magnitudes; guard numeric).
    def _num(s: str) -> float:
        try:
            return float(s)
        except (TypeError, ValueError):
            return 0.0
    out.sort(key=lambda x: -_num(x[0]))
    return [line for _, line in out]


# --------------------------- writer (async) -----------------------------


async def _entity_names_for_doc(rag, doc_id: str) -> list[str]:
    """Return semantic-signal entity names for `doc_id`.

    Filters out low-signal types (amount/date/identifier and pack-
    injected infra nodes) so the summary surfaces people, organizations,
    locations, roles, medications, vehicles — the tokens a natural-
    language query is likely to contain.
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
        if (node.get("entity_type") or "") in _LOW_SIGNAL_TYPES:
            continue
        names.append(name)
    return names


async def _transaction_extras_for_doc(rag, doc_id: str) -> list[str]:
    """Collect Phase 4.5 'Expense summary' nodes for `doc_id`.

    We filter on node name prefix AND source_id to avoid pulling in
    LLM-invented `transaction_category` entities (which share the type
    after taxonomy enforcement but aren't the structured aggregates).
    """
    kg = rag.chunk_entity_relation_graph
    labels = await kg.get_all_labels()
    descriptions: list[str] = []
    for name in labels:
        if not name.startswith("Expense summary "):
            continue
        node = await kg.get_node(name)
        if node is None:
            continue
        if node.get("source_id", "") != doc_id:
            continue
        desc = node.get("description", "").strip()
        if desc:
            # Strip any leading temporal prefix injected by Phase 2.
            if desc.startswith("[sourced:"):
                end = desc.find("]")
                if end != -1:
                    desc = desc[end + 1:].strip()
            descriptions.append(desc)
    return descriptions


async def write_doc_summary_chunks(
    rag,
    store_root: Path,
) -> dict:
    """Upsert one summary chunk per document under `store_root`.

    Returns {docs_scanned, summaries_written}.
    """
    if not store_root.exists():
        return {"docs_scanned": 0, "summaries_written": 0}

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

        entity_names = await _entity_names_for_doc(rag, doc_id)
        extras = await _transaction_extras_for_doc(rag, doc_id)
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
        # lookups via full_doc_id remain consistent. LightRAG reads the
        # KV store for content when building context.
        await rag.text_chunks.upsert(summaries)
        await rag.text_chunks.index_done_callback()

    logger.info(
        "Wrote %d summary chunks across %d docs", len(summaries), scanned,
    )
    return {"docs_scanned": scanned, "summaries_written": len(summaries)}

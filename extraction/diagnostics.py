"""Pure diagnostics — probe LightRAG's retrieval stages without mutating state.

Read-only. Designed to answer: given a question, what did retrieval see
at each stage, and which expected documents survived vs. dropped?

No behavior change anywhere else in the pipeline — this is
instrumentation-only, safe to ship independent of any retrieval fix.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from extraction.provenance import extract_document_ids, parse_document_ids
from extraction.rerank import rerank_func

logger = logging.getLogger(__name__)


@dataclass
class RetrievalStage:
    """One stage of the retrieval trace. Stages are ordered + comparable."""

    stage: str             # "entity_vdb" | "chunks_vdb" | "relationships_vdb" | "rerank"
    hits: list[dict[str, Any]] = field(default_factory=list)
    # Expected-doc retention: None if no expectation provided.
    expected_docs_seen: Optional[list[str]] = None
    expected_docs_missing: Optional[list[str]] = None


@dataclass
class Trace:
    """Full per-query trace: one entry per retrieval stage."""

    question: str
    stages: list[RetrievalStage] = field(default_factory=list)
    expected_documents: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "question": self.question,
            "expected_documents": list(self.expected_documents),
            "stages": [
                {
                    "stage": s.stage,
                    "hits": len(s.hits),
                    "expected_seen": s.expected_docs_seen,
                    "expected_missing": s.expected_docs_missing,
                }
                for s in self.stages
            ],
        }


# --------------------------- expected-doc matching -----------------------


def _filenames_from_ids(doc_ids: Iterable[str], id_to_filename: dict[str, str]) -> list[str]:
    return [id_to_filename.get(i, i) for i in doc_ids]


def _expected_retention(
    hits: list[dict[str, Any]],
    expected_prefixes: list[str],
    id_to_filename: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Return (seen, missing) prefixes based on doc_ids found in hits."""
    if not expected_prefixes:
        return [], []
    # Every hit may expose doc_ids either as a SEP-joined string (graph
    # nodes/edges) or directly as a file_path / chunk id.
    all_doc_ids: set[str] = set()
    for h in hits:
        raw_ids = h.get("document_ids")
        if isinstance(raw_ids, str):
            all_doc_ids.update(parse_document_ids(raw_ids))
        elif isinstance(raw_ids, list):
            all_doc_ids.update(raw_ids)
        raw_fp = h.get("file_path")
        if isinstance(raw_fp, str):
            # file_path can be either an absolute /store/<uuid>/content.md
            # path or a SEP-joined set of them; try both parsers.
            all_doc_ids.update(extract_document_ids(raw_fp))
            all_doc_ids.update(parse_document_ids(raw_fp))
        elif isinstance(raw_fp, list):
            for fp in raw_fp:
                if isinstance(fp, str):
                    all_doc_ids.update(extract_document_ids(fp))
                    all_doc_ids.update(parse_document_ids(fp))
        # Chunks store a `full_doc_id` reference to their source document.
        fd = h.get("full_doc_id")
        if isinstance(fd, str):
            all_doc_ids.add(fd)

    filenames = _filenames_from_ids(all_doc_ids, id_to_filename)
    seen = [p for p in expected_prefixes if any(fn.startswith(p) for fn in filenames)]
    missing = [p for p in expected_prefixes if p not in seen]
    return seen, missing


# ------------------------------ stage probes -----------------------------


async def probe_entity_vdb(rag, question: str, top_k: int = 30) -> list[dict[str, Any]]:
    return await rag.entities_vdb.query(question, top_k=top_k)


async def probe_chunks_vdb(rag, question: str, top_k: int = 30) -> list[dict[str, Any]]:
    return await rag.chunks_vdb.query(question, top_k=top_k)


async def probe_relationships_vdb(rag, question: str, top_k: int = 30) -> list[dict[str, Any]]:
    return await rag.relationships_vdb.query(question, top_k=top_k)


async def probe_rerank(question: str, chunks: list[dict[str, Any]],
                       top_k: int = 20) -> list[dict[str, Any]]:
    """Feed retrieved chunks through the cross-encoder reranker.

    `rerank_func` expects `documents: list[str]` and returns
    `[{"index": i, "relevance_score": s}, ...]`. We map the indices back
    onto the original chunks and attach the score.
    """
    if not chunks:
        return []
    texts = [
        (c.get("content") or c.get("description") or c.get("text") or "")
        for c in chunks
    ]
    indexed = await rerank_func(query=question, documents=texts, top_n=top_k)
    out = []
    for r in indexed:
        idx = r.get("index")
        if idx is None or idx < 0 or idx >= len(chunks):
            continue
        merged = dict(chunks[idx])
        merged["relevance_score"] = r.get("relevance_score")
        out.append(merged)
    return out


# ------------------------------- tracer ----------------------------------


async def trace_query(
    rag,
    question: str,
    *,
    top_k: int = 30,
    rerank_top_k: int = 20,
    expected_documents: Optional[list[str]] = None,
    id_to_filename: Optional[dict[str, str]] = None,
) -> Trace:
    """Probe every retrieval stage for `question`; return a structured trace.

    Does NOT call rag.aquery / the LLM — purely the retrieval layer.
    Cheap and deterministic.
    """
    expected = list(expected_documents or [])
    id_map = dict(id_to_filename or {})
    trace = Trace(question=question, expected_documents=expected)

    # 1. Raw vector retrieval (parallelizable, but keep ordered for readability).
    entities = await probe_entity_vdb(rag, question, top_k=top_k)
    chunks = await probe_chunks_vdb(rag, question, top_k=top_k)
    relations = await probe_relationships_vdb(rag, question, top_k=top_k)

    for stage_name, hits in (
        ("entity_vdb", entities),
        ("chunks_vdb", chunks),
        ("relationships_vdb", relations),
    ):
        seen, missing = _expected_retention(hits, expected, id_map)
        trace.stages.append(RetrievalStage(
            stage=stage_name, hits=hits,
            expected_docs_seen=seen if expected else None,
            expected_docs_missing=missing if expected else None,
        ))

    # 2. Rerank on chunks.
    reranked = await probe_rerank(question, chunks, top_k=rerank_top_k)
    seen, missing = _expected_retention(reranked, expected, id_map)
    trace.stages.append(RetrievalStage(
        stage="rerank",
        hits=reranked,
        expected_docs_seen=seen if expected else None,
        expected_docs_missing=missing if expected else None,
    ))

    return trace

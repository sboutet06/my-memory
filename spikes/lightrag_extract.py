"""Layer 3 spike: entity extraction with LightRAG on V0-ingested docs.

Goal: validate whether LightRAG produces useful entities/relationships
from our `content.md` outputs, and answer the parked `degraded`-quality
debt — are recovered OCR dumps good enough for the graph layer, or do
they need a dedicated clean-up branch?

Setup:
- LLM: Google Gemini 2.5 Flash via OpenRouter (OPEN_ROUTER_API_KEY).
- Embeddings: local sentence-transformers multilingual MiniLM (384-dim).
- Corpus: one `rich` invoice + one `degraded` passport.
- Working dir: `spikes/lightrag_out/` (gitignored).

Run: `python -m spikes.lightrag_extract`
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc, setup_logger
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parent.parent
STORE = REPO_ROOT / "store"
WORKING_DIR = REPO_ROOT / "spikes" / "lightrag_out"

LLM_MODEL = "google/gemini-2.5-flash"
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384

# (document_id prefix, human label) — full ids resolved at runtime.
TARGETS: list[tuple[str, str]] = [
    ("07818304", "invoice (rich)"),
    ("555fbe67", "passport (degraded)"),
]

QUERIES = [
    "Liste les personnes nommées dans les documents avec leur rôle.",
    "Quels sont les montants ou dates mentionnés ?",
    "Quelles organisations ou entreprises apparaissent ?",
]

logger = logging.getLogger("spike.lightrag")


def resolve_doc_path(prefix: str) -> Path:
    matches = [d for d in STORE.iterdir() if d.is_dir() and d.name.startswith(prefix)]
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly 1 doc matching {prefix!r}, got {len(matches)}")
    md = matches[0] / "content.md"
    if not md.is_file():
        raise SystemExit(f"Missing content.md in {matches[0]}")
    return md


async def llm_model_func(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list | None = None,
    keyword_extraction: bool = False,
    **kwargs,
) -> str:
    return await openai_complete_if_cache(
        LLM_MODEL,
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        api_key=os.environ["OPEN_ROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        **kwargs,
    )


def make_embedding_func() -> EmbeddingFunc:
    model = SentenceTransformer(EMBED_MODEL)

    async def embed(texts: list[str]) -> np.ndarray:
        # SentenceTransformer is CPU/GPU-sync; run in default executor.
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: model.encode(
                texts, convert_to_numpy=True, normalize_embeddings=True
            ),
        )

    return EmbeddingFunc(
        embedding_dim=EMBED_DIM,
        func=embed,
    )


async def build_rag() -> LightRAG:
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    rag = LightRAG(
        working_dir=str(WORKING_DIR),
        llm_model_func=llm_model_func,
        embedding_func=make_embedding_func(),
    )
    await rag.initialize_storages()
    return rag


async def ingest_targets(rag: LightRAG) -> None:
    for prefix, label in TARGETS:
        md_path = resolve_doc_path(prefix)
        text = md_path.read_text(encoding="utf-8")
        logger.info("Inserting %s (%s, %d chars)", md_path.parent.name[:8], label, len(text))
        await rag.ainsert(text, ids=[md_path.parent.name], file_paths=[str(md_path)])


async def dump_graph_summary(rag: LightRAG) -> dict:
    kg = rag.chunk_entity_relation_graph
    labels = await kg.get_all_labels()
    summary: dict = {"entity_count": len(labels), "entities": []}
    for name in labels:
        node = await kg.get_node(name)
        if node is None:
            continue
        edges = await kg.get_node_edges(name) or []
        summary["entities"].append(
            {
                "name": name,
                "type": node.get("entity_type"),
                "description": (node.get("description") or "")[:200],
                "degree": len(edges),
            }
        )
    summary["entities"].sort(key=lambda e: e["degree"], reverse=True)
    return summary


async def run_queries(rag: LightRAG) -> list[dict]:
    results = []
    for q in QUERIES:
        answer = await rag.aquery(q, param=QueryParam(mode="hybrid"))
        results.append({"q": q, "a": answer})
    return results


async def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    if "OPEN_ROUTER_API_KEY" not in os.environ:
        print("ERROR: OPEN_ROUTER_API_KEY not set (check .env)", file=sys.stderr)
        return 2

    setup_logger("lightrag", level="WARNING")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    rag = await build_rag()
    try:
        await ingest_targets(rag)
        summary = await dump_graph_summary(rag)
        print("\n=== Extracted graph ===")
        print(json.dumps(summary, indent=2, ensure_ascii=False))

        answers = await run_queries(rag)
        print("\n=== Queries ===")
        for a in answers:
            print(f"\nQ: {a['q']}\nA: {a['a']}")
    finally:
        await rag.finalize_storages()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

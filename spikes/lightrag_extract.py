"""Layer 3 spike: entity extraction with LightRAG on V0-ingested docs.

Goal: validate whether LightRAG produces useful entities/relationships
from our `content.md` outputs, and observe how the gaps surfaced by the
2-doc spike (fragmentation, noise entities, typing inconsistency) scale
on the full ingested corpus.

Setup:
- LLM: Google Gemini 2.5 Flash via OpenRouter (OPEN_ROUTER_API_KEY).
- Embeddings: local sentence-transformers multilingual MiniLM (384-dim).
- Corpus: every document currently in `store/`.
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

QUERIES = [
    "Liste les personnes nommées dans l'ensemble des documents avec leur rôle et le document qui les mentionne.",
    "Quelles organisations ou entreprises apparaissent, et dans quels documents ?",
    "Récapitule les informations fiscales disponibles (impôts, déclarations, montants).",
    "Quels sont les documents relatifs à un bien immobilier ou un compromis de vente ?",
]

logger = logging.getLogger("spike.lightrag")


def discover_store_docs() -> list[tuple[Path, dict]]:
    """Return (content_md_path, metadata_dict) for every doc in store/."""
    out: list[tuple[Path, dict]] = []
    for entry in sorted(STORE.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".tmp-"):
            continue
        meta_path = entry / "metadata.json"
        md_path = entry / "content.md"
        if not (meta_path.is_file() and md_path.is_file()):
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        out.append((md_path, meta))
    return out


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
    docs = discover_store_docs()
    if not docs:
        raise SystemExit("No ingested docs found in store/")
    texts, ids, file_paths = [], [], []
    for md_path, meta in docs:
        text = md_path.read_text(encoding="utf-8")
        logger.info(
            "Queuing %s [%s] %s (%d chars)",
            meta["document_id"][:8],
            meta.get("extraction_quality", "?"),
            meta["original_filename"],
            len(text),
        )
        texts.append(text)
        ids.append(meta["document_id"])
        file_paths.append(str(md_path))
    logger.info("Inserting %d documents into LightRAG", len(texts))
    await rag.ainsert(texts, ids=ids, file_paths=file_paths)


async def dump_graph_summary(rag: LightRAG, top_n: int = 40) -> dict:
    kg = rag.chunk_entity_relation_graph
    labels = await kg.get_all_labels()
    rows = []
    for name in labels:
        node = await kg.get_node(name)
        if node is None:
            continue
        edges = await kg.get_node_edges(name) or []
        rows.append(
            {
                "name": name,
                "type": node.get("entity_type"),
                "degree": len(edges),
            }
        )
    rows.sort(key=lambda e: e["degree"], reverse=True)

    type_hist: dict[str, int] = {}
    for r in rows:
        type_hist[r["type"] or "null"] = type_hist.get(r["type"] or "null", 0) + 1

    isolated = sum(1 for r in rows if r["degree"] == 0)
    return {
        "entity_count": len(rows),
        "with_edges": len(rows) - isolated,
        "isolated": isolated,
        "type_histogram": dict(sorted(type_hist.items(), key=lambda kv: -kv[1])),
        "top_entities": rows[:top_n],
    }


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

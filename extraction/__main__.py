"""CLI: `python -m extraction {extract,query} ...`."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from lightrag import QueryParam

from extraction.config import ExtractionConfig
from extraction.graph import (
    DEFAULT_WORKING_DIR,
    build_rag,
    discover_store_docs,
    extract_documents,
    graph_stats,
    post_process,
)
from extraction.provenance import extract_document_ids

logger = logging.getLogger("extraction")

QUERY_MODES = ("hybrid", "local", "global", "naive", "mix")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m extraction")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser("extract", help="Extract entities/relations from ingested docs")
    p_extract.add_argument("--store", type=Path, default=Path("store"))
    p_extract.add_argument(
        "--working-dir", type=Path, default=DEFAULT_WORKING_DIR,
        help=f"LightRAG working directory (default: {DEFAULT_WORKING_DIR})",
    )
    p_extract.add_argument("-v", "--verbose", action="store_true")

    p_query = sub.add_parser("query", help="Query the extracted knowledge graph")
    p_query.add_argument("question", type=str, help="Natural-language question")
    p_query.add_argument(
        "--mode", choices=QUERY_MODES, default="hybrid",
        help=f"Retrieval mode (default: hybrid). One of: {', '.join(QUERY_MODES)}",
    )
    p_query.add_argument(
        "--working-dir", type=Path, default=DEFAULT_WORKING_DIR,
        help=f"LightRAG working directory (default: {DEFAULT_WORKING_DIR})",
    )
    p_query.add_argument(
        "--json", action="store_true",
        help="Emit JSON with answer + referenced document_ids",
    )
    p_query.add_argument("-v", "--verbose", action="store_true")

    return parser


async def _run_extract(store_root: Path, working_dir: Path) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    docs = discover_store_docs(store_root)
    if not docs:
        print(f"No ingested docs found under {store_root}", file=sys.stderr)
        return 1

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        inserted = await extract_documents(rag, docs)
        pp_stats = await post_process(rag, allowed_entity_types=config.entity_types)
        stats = await graph_stats(rag)
    finally:
        await rag.finalize_storages()

    report = {
        "inserted": inserted,
        "post_process": pp_stats,
        "graph": stats,
        "config": {
            "llm_model": config.llm_model,
            "embed_model": config.embed_model,
            "entity_types": config.entity_types,
            "language": config.language,
        },
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


async def _run_query(question: str, mode: str, working_dir: Path, as_json: bool) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    if not working_dir.exists():
        print(
            f"No extraction store at {working_dir}. Run `extract` first.",
            file=sys.stderr,
        )
        return 1

    rag = await build_rag(working_dir=working_dir, config=config)
    try:
        answer = await rag.aquery(
            question,
            param=QueryParam(
                mode=mode,
                user_prompt=config.temporal_user_prompt,
            ),
        )
    finally:
        await rag.finalize_storages()

    doc_ids = extract_document_ids(answer)

    if as_json:
        print(json.dumps(
            {
                "question": question,
                "mode": mode,
                "answer": answer,
                "document_ids": doc_ids,
            },
            indent=2,
            ensure_ascii=False,
        ))
    else:
        print(answer)
        if doc_ids:
            print("\n=== Referenced documents ===")
            for d in doc_ids:
                print(f"  - {d}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.cmd == "extract":
        return asyncio.run(_run_extract(args.store, args.working_dir))
    if args.cmd == "query":
        return asyncio.run(_run_query(args.question, args.mode, args.working_dir, args.json))

    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""CLI: `python -m extraction [--store PATH] [--working-dir PATH]`."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from extraction.config import ExtractionConfig
from extraction.graph import (
    DEFAULT_WORKING_DIR,
    build_rag,
    discover_store_docs,
    extract_documents,
    graph_stats,
    post_process,
)

logger = logging.getLogger("extraction")


async def run(store_root: Path, working_dir: Path) -> int:
    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()  # fail fast

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m extraction")
    parser.add_argument("--store", type=Path, default=Path("store"))
    parser.add_argument(
        "--working-dir", type=Path, default=DEFAULT_WORKING_DIR,
        help=f"LightRAG working directory (default: {DEFAULT_WORKING_DIR})",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    return asyncio.run(run(args.store, args.working_dir))


if __name__ == "__main__":
    sys.exit(main())

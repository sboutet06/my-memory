"""CLI: `python -m ingestion <file-or-folder> [--store STORE] [-v]`."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ingestion.ingest import (
    DEFAULT_STORE_ROOT,
    ingest_document,
)
from ingestion.models import IngestionResult, IngestionStatus

logger = logging.getLogger("ingestion")


def _format(result: IngestionResult, source: Path) -> str:
    status = result.status.value
    head = f"[{status}] {source.name}"
    match result.status:
        case IngestionStatus.INGESTED:
            quality = result.metadata.extraction_quality.value if result.metadata else "?"
            return f"{head} → {result.document_id} (quality={quality}, {result.storage_path})"
        case IngestionStatus.DUPLICATE:
            return f"{head} → existing {result.document_id}"
        case IngestionStatus.UNSUPPORTED | IngestionStatus.FAILED:
            return f"{head}: {result.message}"
    return head


def _ingest_batch(folder: Path, store_root: Path) -> int:
    files = sorted(p for p in folder.iterdir() if p.is_file())
    if not files:
        print(f"No files in {folder}")
        return 0

    failures = 0
    for fp in files:
        try:
            result = ingest_document(fp, store_root=store_root)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unhandled error on %s", fp)
            print(f"[error] {fp.name}: {exc}")
            failures += 1
            continue
        print(_format(result, fp))
        if result.status == IngestionStatus.FAILED:
            failures += 1
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingestion")
    parser.add_argument("target", type=Path, help="File or folder to ingest")
    parser.add_argument(
        "--store", type=Path, default=DEFAULT_STORE_ROOT,
        help=f"Store root (default: {DEFAULT_STORE_ROOT})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG logs")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    target: Path = args.target
    if not target.exists():
        print(f"Not found: {target}", file=sys.stderr)
        return 2

    if target.is_dir():
        return 1 if _ingest_batch(target, args.store) else 0

    result = ingest_document(target, store_root=args.store)
    print(_format(result, target))
    return 0 if result.status in {IngestionStatus.INGESTED, IngestionStatus.DUPLICATE} else 1


if __name__ == "__main__":
    sys.exit(main())

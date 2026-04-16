"""Filesystem storage: atomic staging, dedup scan, persistence."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from ingestion.models import DocumentMetadata

logger = logging.getLogger(__name__)

METADATA_FILENAME = "metadata.json"
CONTENT_JSON_FILENAME = "content.json"
CONTENT_MD_FILENAME = "content.md"
_TMP_PREFIX = ".tmp-"


class StorageError(RuntimeError):
    """Raised on unrecoverable storage failures."""


def find_duplicate(store_root: Path, content_hash: str) -> Optional[DocumentMetadata]:
    """Scan `store_root/*/metadata.json` for a matching hash. Returns first match."""
    if not store_root.exists():
        return None
    for entry in sorted(store_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith(_TMP_PREFIX):
            continue
        meta_path = entry / METADATA_FILENAME
        if not meta_path.is_file():
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable metadata %s: %s", meta_path, exc)
            continue
        if data.get("content_hash") == content_hash:
            try:
                return DocumentMetadata.model_validate(data)
            except ValidationError as exc:
                logger.warning("Invalid metadata at %s: %s", meta_path, exc)
                continue
    return None


def persist_document(
    *,
    store_root: Path,
    metadata: DocumentMetadata,
    docling_json: dict,
    docling_markdown: str,
    source_path: Path,
) -> Path:
    """Atomically persist all four artifacts under `store_root/{document_id}/`.

    Strategy: write everything to a sibling tmp dir, then `os.rename` to final.
    On any exception, the tmp dir is removed; final dir is never partially populated.
    """
    store_root.mkdir(parents=True, exist_ok=True)
    final_dir = store_root / metadata.document_id
    if final_dir.exists():
        raise StorageError(f"Target already exists: {final_dir}")

    tmp_dir = store_root / f"{_TMP_PREFIX}{metadata.document_id}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    try:
        (tmp_dir / METADATA_FILENAME).write_text(
            metadata.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (tmp_dir / CONTENT_JSON_FILENAME).write_text(
            json.dumps(docling_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (tmp_dir / CONTENT_MD_FILENAME).write_text(docling_markdown, encoding="utf-8")

        ext = source_path.suffix  # preserves leading "."; empty if none
        original_target = tmp_dir / f"original{ext}"
        shutil.copy2(source_path, original_target)

        tmp_dir.rename(final_dir)
        return final_dir
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

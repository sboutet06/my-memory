"""Filesystem storage: atomic staging, dedup scan, persistence, versioning."""
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
VERSIONS_DIRNAME = "versions"
CURRENT_POINTER_FILENAME = "current"
_TMP_PREFIX = ".tmp-"

# Files that constitute one version's artifact set at the doc root.
# `original.<ext>` is matched dynamically.
_VERSIONED_NAMES = (METADATA_FILENAME, CONTENT_JSON_FILENAME, CONTENT_MD_FILENAME)


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


def find_existing_at_path(store_root: Path, original_path: str) -> Optional[DocumentMetadata]:
    """Find the *current* document whose source path matches `original_path`.

    Phase 8b.1 identity rule: re-ingest of the same resolved source path is
    treated as a new version of the same document. Path equality is exact —
    callers should pass the resolved absolute path.

    Skips `.tmp-*` staging dirs and `versions/<n>/` archives (only the
    top-level metadata.json is consulted, which always represents the
    current version).
    """
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
        if data.get("original_path") == original_path:
            try:
                return DocumentMetadata.model_validate(data)
            except ValidationError as exc:
                logger.warning("Invalid metadata at %s: %s", meta_path, exc)
                continue
    return None


def read_current_version(store_root: Path, document_id: str) -> int:
    """Return the active version number for `document_id`.

    `current` pointer file holds the version integer. Pre-versioning docs
    have no pointer file → version 1.
    """
    pointer = store_root / document_id / CURRENT_POINTER_FILENAME
    if not pointer.is_file():
        return 1
    try:
        return int(pointer.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        logger.warning("Bad current pointer at %s: %s", pointer, exc)
        return 1


def _write_current_pointer(doc_dir: Path, version: int) -> None:
    pointer = doc_dir / CURRENT_POINTER_FILENAME
    tmp = doc_dir / f".{CURRENT_POINTER_FILENAME}.tmp"
    tmp.write_text(f"{version}\n", encoding="utf-8")
    tmp.replace(pointer)


def archive_current_version(store_root: Path, document_id: str, version: int) -> Path:
    """Move the current artifacts under `versions/<version>/`, leaving the
    doc dir empty so the next persist can lay down v(version+1).

    Does NOT update the `current` pointer — caller does that AFTER the new
    version's `persist_document` succeeds, to keep a write failure on the
    new version from leaving an inconsistent pointer.

    Raises:
        FileNotFoundError: doc dir missing.
        FileExistsError: target `versions/<version>/` already populated.
    """
    doc_dir = store_root / document_id
    if not doc_dir.is_dir():
        raise FileNotFoundError(f"Document dir absent: {doc_dir}")

    archive = doc_dir / VERSIONS_DIRNAME / str(version)
    if archive.exists():
        raise FileExistsError(f"Version archive already exists: {archive}")
    archive.mkdir(parents=True)

    moved_anything = False
    for name in _VERSIONED_NAMES:
        src = doc_dir / name
        if src.is_file():
            shutil.move(str(src), str(archive / name))
            moved_anything = True

    # Move any `original.*` (extension is dynamic).
    for src in doc_dir.iterdir():
        if src.is_file() and src.name.startswith("original."):
            shutil.move(str(src), str(archive / src.name))
            moved_anything = True

    if not moved_anything:
        # Empty doc dir — clean up the empty archive we just made.
        archive.rmdir()
        # Best-effort cleanup of the parent versions/ if also empty.
        versions_root = doc_dir / VERSIONS_DIRNAME
        if versions_root.is_dir() and not any(versions_root.iterdir()):
            versions_root.rmdir()
        raise FileNotFoundError(
            f"Nothing to archive at {doc_dir}: no artifacts to move",
        )

    return archive


def persist_document(
    *,
    store_root: Path,
    metadata: DocumentMetadata,
    docling_json: dict,
    docling_markdown: str,
    source_path: Path,
    is_update: bool = False,
) -> Path:
    """Atomically persist all four artifacts under `store_root/{document_id}/`.

    Strategy: write everything to a sibling tmp dir, then `os.rename` to final.
    On any exception, the tmp dir is removed; final dir is never partially populated.

    `is_update=True` allows persisting into an existing `doc_id` whose
    artifacts have just been archived to `versions/<n>/` — used by the
    Phase 8b.1 re-ingest flow. Default `is_update=False` preserves the
    "no overwrite without warning" behaviour for fresh docs.

    On a successful update, the `current` pointer is bumped to
    `read_current_version(...) + 1`.
    """
    store_root.mkdir(parents=True, exist_ok=True)
    final_dir = store_root / metadata.document_id

    if is_update:
        if not final_dir.is_dir():
            raise StorageError(
                f"Update requested but doc dir missing: {final_dir}",
            )
        # Top-level artifacts must have been archived first.
        for name in _VERSIONED_NAMES:
            if (final_dir / name).exists():
                raise StorageError(
                    f"Update requires top-level {name} to be archived first",
                )
    else:
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

        if is_update:
            # Move artifacts INTO the existing dir (which already holds versions/).
            for name in _VERSIONED_NAMES:
                shutil.move(str(tmp_dir / name), str(final_dir / name))
            shutil.move(str(original_target), str(final_dir / original_target.name))
            tmp_dir.rmdir()
            # Bump current pointer to (existing + 1).
            new_version = read_current_version(store_root, metadata.document_id) + 1
            _write_current_pointer(final_dir, new_version)
        else:
            tmp_dir.rename(final_dir)
        return final_dir
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

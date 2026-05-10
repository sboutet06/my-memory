"""Phase 8b.1 — re-ingest archives prior version, current pointer advances.

Identity rule (decided 2026-05-10): two ingests with the same resolved
`original_path` and *different* content_hash are treated as v1 / v2 of the
same document. Same `document_id`, prior artifacts move to
`versions/<n>/`, `current` pointer file at the doc dir holds the active
version number.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingestion.models import DocumentMetadata, SourceType
from ingestion.storage import (
    CONTENT_JSON_FILENAME,
    CONTENT_MD_FILENAME,
    CURRENT_POINTER_FILENAME,
    METADATA_FILENAME,
    VERSIONS_DIRNAME,
    archive_current_version,
    find_existing_at_path,
    persist_document,
    read_current_version,
)


_DOC_ID = "11111111-1111-4111-8111-111111111111"


def _meta(*, hash_: str, doc_id: str = _DOC_ID, path: str = "/abs/x.pdf") -> DocumentMetadata:
    return DocumentMetadata(
        document_id=doc_id,
        content_hash=hash_,
        original_filename="x.pdf",
        original_path=path,
        mime_type="application/pdf",
        size_bytes=10,
        ingested_at=datetime.now(timezone.utc),
        docling_version="2.88.0",
        processing_duration_ms=5,
        source_type=SourceType.FILESYSTEM,
    )


# --- find_existing_at_path -------------------------------------------------


def test_find_existing_at_path_empty_store(tmp_path: Path) -> None:
    assert find_existing_at_path(tmp_path / "store", "/abs/x.pdf") is None


def test_find_existing_at_path_hit(tmp_path: Path) -> None:
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF-1.4 v1\n")
    persist_document(
        store_root=store,
        metadata=_meta(hash_="a" * 64, path="/abs/x.pdf"),
        docling_json={}, docling_markdown="", source_path=src,
    )
    hit = find_existing_at_path(store, "/abs/x.pdf")
    assert hit is not None
    assert hit.document_id == _DOC_ID
    assert hit.content_hash == "a" * 64


def test_find_existing_at_path_miss_when_path_differs(tmp_path: Path) -> None:
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    persist_document(
        store_root=store,
        metadata=_meta(hash_="a" * 64, path="/abs/x.pdf"),
        docling_json={}, docling_markdown="", source_path=src,
    )
    assert find_existing_at_path(store, "/abs/different.pdf") is None


def test_find_existing_at_path_skips_archived_versions(tmp_path: Path) -> None:
    """A versioned doc returns the *current* metadata, not historical."""
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF v1\n")
    persist_document(
        store_root=store,
        metadata=_meta(hash_="a" * 64, path="/abs/x.pdf"),
        docling_json={}, docling_markdown="", source_path=src,
    )
    # Simulate v2 swap.
    archive_current_version(store, _DOC_ID, version=1)
    src.write_bytes(b"%PDF v2 more bytes\n")
    persist_document(
        store_root=store,
        metadata=_meta(hash_="b" * 64, path="/abs/x.pdf"),
        docling_json={}, docling_markdown="", source_path=src,
        is_update=True,
    )

    hit = find_existing_at_path(store, "/abs/x.pdf")
    assert hit is not None
    assert hit.content_hash == "b" * 64  # current (v2), not archived v1


# --- read_current_version --------------------------------------------------


def test_read_current_version_legacy_doc_returns_1(tmp_path: Path) -> None:
    """Pre-versioning docs (no `current` pointer file) are version 1."""
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF\n")
    persist_document(
        store_root=store,
        metadata=_meta(hash_="a" * 64),
        docling_json={}, docling_markdown="", source_path=src,
    )
    assert read_current_version(store, _DOC_ID) == 1


def test_read_current_version_after_archive(tmp_path: Path) -> None:
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF v1\n")
    persist_document(
        store_root=store,
        metadata=_meta(hash_="a" * 64),
        docling_json={}, docling_markdown="", source_path=src,
    )
    archive_current_version(store, _DOC_ID, version=1)
    src.write_bytes(b"%PDF v2 bytes\n")
    persist_document(
        store_root=store,
        metadata=_meta(hash_="b" * 64),
        docling_json={}, docling_markdown="", source_path=src,
        is_update=True,
    )
    assert read_current_version(store, _DOC_ID) == 2


# --- archive_current_version -----------------------------------------------


def test_archive_current_version_moves_artifacts(tmp_path: Path) -> None:
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF v1 bytes\n")
    persist_document(
        store_root=store,
        metadata=_meta(hash_="a" * 64),
        docling_json={"v": 1}, docling_markdown="# v1", source_path=src,
    )

    archive_current_version(store, _DOC_ID, version=1)

    doc_dir = store / _DOC_ID
    archive = doc_dir / VERSIONS_DIRNAME / "1"
    assert archive.is_dir()
    assert (archive / METADATA_FILENAME).is_file()
    assert (archive / CONTENT_JSON_FILENAME).is_file()
    assert (archive / CONTENT_MD_FILENAME).is_file()
    assert (archive / "original.pdf").is_file()
    # Top-level artifacts cleared (will be replaced by next persist).
    assert not (doc_dir / METADATA_FILENAME).exists()
    assert not (doc_dir / CONTENT_JSON_FILENAME).exists()
    assert not (doc_dir / CONTENT_MD_FILENAME).exists()
    # current pointer not yet bumped — caller does that AFTER persist.
    # But the version-1 archive must be readable and intact.
    assert json.loads((archive / CONTENT_JSON_FILENAME).read_text()) == {"v": 1}


def test_archive_then_persist_yields_two_versions(tmp_path: Path) -> None:
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"

    src.write_bytes(b"%PDF v1\n")
    persist_document(
        store_root=store, metadata=_meta(hash_="a" * 64),
        docling_json={"v": 1}, docling_markdown="# v1", source_path=src,
    )

    archive_current_version(store, _DOC_ID, version=1)
    src.write_bytes(b"%PDF v2 different bytes\n")
    persist_document(
        store_root=store, metadata=_meta(hash_="b" * 64),
        docling_json={"v": 2}, docling_markdown="# v2", source_path=src,
        is_update=True,
    )

    doc_dir = store / _DOC_ID
    # Current points at v2.
    assert json.loads((doc_dir / CONTENT_JSON_FILENAME).read_text()) == {"v": 2}
    # v1 still readable.
    v1 = doc_dir / VERSIONS_DIRNAME / "1"
    assert json.loads((v1 / CONTENT_JSON_FILENAME).read_text()) == {"v": 1}


def test_archive_missing_doc_raises(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    with pytest.raises(FileNotFoundError):
        archive_current_version(store, "no-such-id", version=1)


def test_archive_target_collision_raises(tmp_path: Path) -> None:
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF\n")
    persist_document(
        store_root=store, metadata=_meta(hash_="a" * 64),
        docling_json={}, docling_markdown="", source_path=src,
    )
    # Simulate a stale versions/1 dir.
    (store / _DOC_ID / VERSIONS_DIRNAME / "1").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        archive_current_version(store, _DOC_ID, version=1)


# --- current pointer file --------------------------------------------------


def test_current_pointer_file_format(tmp_path: Path) -> None:
    """`current` is a plain text file containing just the integer version."""
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF\n")
    persist_document(
        store_root=store, metadata=_meta(hash_="a" * 64),
        docling_json={}, docling_markdown="", source_path=src,
    )
    archive_current_version(store, _DOC_ID, version=1)
    src.write_bytes(b"%PDF v2\n")
    persist_document(
        store_root=store, metadata=_meta(hash_="b" * 64),
        docling_json={}, docling_markdown="", source_path=src,
        is_update=True,
    )

    pointer = store / _DOC_ID / CURRENT_POINTER_FILENAME
    assert pointer.is_file()
    assert pointer.read_text(encoding="utf-8").strip() == "2"

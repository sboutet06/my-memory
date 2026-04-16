"""Unit tests for dedup scan and atomic persistence."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingestion.models import DocumentMetadata, SourceType
from ingestion.storage import (
    CONTENT_JSON_FILENAME,
    CONTENT_MD_FILENAME,
    METADATA_FILENAME,
    StorageError,
    find_duplicate,
    persist_document,
)


def _make_meta(hash_: str = "a" * 64, doc_id: str = "11111111-1111-4111-8111-111111111111") -> DocumentMetadata:
    return DocumentMetadata(
        document_id=doc_id,
        content_hash=hash_,
        original_filename="x.pdf",
        original_path="/tmp/x.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        ingested_at=datetime.now(timezone.utc),
        docling_version="2.88.0",
        processing_duration_ms=5,
        source_type=SourceType.FILESYSTEM,
    )


def test_find_duplicate_empty_store(tmp_path: Path) -> None:
    assert find_duplicate(tmp_path / "store", "deadbeef") is None


def test_persist_then_find_duplicate_hit(tmp_path: Path) -> None:
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    meta = _make_meta()

    final = persist_document(
        store_root=store,
        metadata=meta,
        docling_json={"k": "v"},
        docling_markdown="# hi",
        source_path=src,
    )

    assert final == store / meta.document_id
    assert (final / METADATA_FILENAME).is_file()
    assert (final / CONTENT_JSON_FILENAME).is_file()
    assert (final / CONTENT_MD_FILENAME).is_file()
    assert (final / "original.pdf").is_file()

    # Content checks.
    assert json.loads((final / CONTENT_JSON_FILENAME).read_text()) == {"k": "v"}
    assert (final / CONTENT_MD_FILENAME).read_text() == "# hi"
    assert (final / "original.pdf").read_bytes() == src.read_bytes()

    hit = find_duplicate(store, meta.content_hash)
    assert hit is not None
    assert hit.document_id == meta.document_id


def test_persist_rejects_existing_target(tmp_path: Path) -> None:
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    meta = _make_meta()

    persist_document(
        store_root=store, metadata=meta,
        docling_json={}, docling_markdown="", source_path=src,
    )

    with pytest.raises(StorageError):
        persist_document(
            store_root=store, metadata=meta,
            docling_json={}, docling_markdown="", source_path=src,
        )


def test_persist_failure_leaves_no_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "store"
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    meta = _make_meta()

    # Force copy2 to blow up after metadata+json+md are written.
    import ingestion.storage as storage_mod

    def boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(storage_mod.shutil, "copy2", boom)

    with pytest.raises(OSError, match="disk full"):
        persist_document(
            store_root=store, metadata=meta,
            docling_json={}, docling_markdown="", source_path=src,
        )

    # Final dir must not exist; tmp dir must be cleaned up.
    assert not (store / meta.document_id).exists()
    leftovers = [p for p in store.iterdir() if p.name.startswith(".tmp-")]
    assert leftovers == []


def test_find_duplicate_skips_tmp_dirs(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    tmp = store / ".tmp-abc"
    tmp.mkdir()
    (tmp / METADATA_FILENAME).write_text(
        _make_meta(hash_="f" * 64).model_dump_json(), encoding="utf-8",
    )
    assert find_duplicate(store, "f" * 64) is None


def test_find_duplicate_tolerates_bad_metadata(tmp_path: Path) -> None:
    store = tmp_path / "store"
    (store / "broken").mkdir(parents=True)
    (store / "broken" / METADATA_FILENAME).write_text("{not json", encoding="utf-8")
    assert find_duplicate(store, "x") is None

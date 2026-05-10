"""Phase 8b.1 — re-ingest path-based versioning at the orchestrator level.

Verifies `ingest_document` detects same-source-path re-ingest with
changed content, archives the prior version, and persists the new one
under the same `document_id`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingestion import ingest as ingest_mod
from ingestion.ingest import ingest_document
from ingestion.models import IngestionStatus
from ingestion.storage import (
    CONTENT_JSON_FILENAME,
    CURRENT_POINTER_FILENAME,
    METADATA_FILENAME,
    VERSIONS_DIRNAME,
)


@pytest.fixture
def fake_docling(monkeypatch: pytest.MonkeyPatch):
    """Stub Docling so tests don't depend on the real converter."""
    counter = {"n": 0}

    def _stub(path: Path):
        counter["n"] += 1
        # Embed counter so v1 vs v2 markdown differs.
        return (
            {"schema": "docling", "name": path.name, "v": counter["n"]},
            f"# {path.name}\n\nstub body v{counter['n']}",
            7,
        )

    monkeypatch.setattr(ingest_mod, "_run_docling", _stub)
    return counter


def test_reingest_changed_content_returns_updated(tmp_path: Path, fake_docling) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF v1\n")
    store = tmp_path / "store"

    first = ingest_document(src, store_root=store, classify=False)
    assert first.status == IngestionStatus.INGESTED

    src.write_bytes(b"%PDF v2 different bytes\n")
    second = ingest_document(src, store_root=store, classify=False)

    assert second.status == IngestionStatus.UPDATED
    assert second.document_id == first.document_id


def test_reingest_archives_v1_under_versions(tmp_path: Path, fake_docling) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF v1\n")
    store = tmp_path / "store"

    first = ingest_document(src, store_root=store, classify=False)

    src.write_bytes(b"%PDF v2 different\n")
    ingest_document(src, store_root=store, classify=False)

    archive = store / first.document_id / VERSIONS_DIRNAME / "1"
    assert archive.is_dir()
    assert (archive / METADATA_FILENAME).is_file()
    assert (archive / CONTENT_JSON_FILENAME).is_file()
    assert (archive / "original.pdf").is_file()
    # v1 content distinguishable from v2.
    archived = json.loads((archive / CONTENT_JSON_FILENAME).read_text())
    assert archived["v"] == 1


def test_reingest_advances_current_pointer_to_2(tmp_path: Path, fake_docling) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF v1\n")
    store = tmp_path / "store"

    first = ingest_document(src, store_root=store, classify=False)
    src.write_bytes(b"%PDF v2 different\n")
    ingest_document(src, store_root=store, classify=False)

    pointer = store / first.document_id / CURRENT_POINTER_FILENAME
    assert pointer.read_text(encoding="utf-8").strip() == "2"


def test_reingest_top_level_holds_v2_artifacts(tmp_path: Path, fake_docling) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF v1\n")
    store = tmp_path / "store"

    first = ingest_document(src, store_root=store, classify=False)
    src.write_bytes(b"%PDF v2\n")
    ingest_document(src, store_root=store, classify=False)

    top = store / first.document_id / CONTENT_JSON_FILENAME
    current = json.loads(top.read_text())
    assert current["v"] == 2  # latest, not archived


def test_same_path_same_content_still_duplicate(tmp_path: Path, fake_docling) -> None:
    """Identical bytes at same path → DUPLICATE, no version archive."""
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF v1\n")
    store = tmp_path / "store"

    first = ingest_document(src, store_root=store, classify=False)
    second = ingest_document(src, store_root=store, classify=False)

    assert second.status == IngestionStatus.DUPLICATE
    assert second.document_id == first.document_id
    versions = store / first.document_id / VERSIONS_DIRNAME
    assert not versions.exists()


def test_different_path_creates_new_doc(tmp_path: Path, fake_docling) -> None:
    """Different path with different content → fresh doc, no archive."""
    src1 = tmp_path / "a.pdf"
    src2 = tmp_path / "b.pdf"
    src1.write_bytes(b"%PDF a\n")
    src2.write_bytes(b"%PDF b\n")
    store = tmp_path / "store"

    r1 = ingest_document(src1, store_root=store, classify=False)
    r2 = ingest_document(src2, store_root=store, classify=False)

    assert r1.status == IngestionStatus.INGESTED
    assert r2.status == IngestionStatus.INGESTED
    assert r1.document_id != r2.document_id


def test_three_versions_all_archived(tmp_path: Path, fake_docling) -> None:
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF v1\n")
    store = tmp_path / "store"

    first = ingest_document(src, store_root=store, classify=False)
    src.write_bytes(b"%PDF v2 bytes\n")
    ingest_document(src, store_root=store, classify=False)
    src.write_bytes(b"%PDF v3 different bytes again\n")
    ingest_document(src, store_root=store, classify=False)

    doc_dir = store / first.document_id
    assert (doc_dir / VERSIONS_DIRNAME / "1").is_dir()
    assert (doc_dir / VERSIONS_DIRNAME / "2").is_dir()
    assert (doc_dir / CURRENT_POINTER_FILENAME).read_text().strip() == "3"

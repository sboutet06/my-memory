"""Tests for the `ingest_document` orchestrator.

Docling is stubbed via monkeypatch in unit tests. A single integration test
runs the real Docling pipeline against `raw/Proposition auto.pdf` — skipped
if the file is missing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ingestion import ingest as ingest_mod
from ingestion.ingest import ingest_document
from ingestion.models import ExtractionQuality, IngestionStatus

RAW_DEMO = Path(__file__).resolve().parent.parent / "raw" / "Proposition auto.pdf"


@pytest.fixture
def fake_docling(monkeypatch: pytest.MonkeyPatch):
    """Replace `_run_docling` with a deterministic stub."""
    def _stub(path: Path):
        return ({"schema": "docling", "name": path.name}, f"# {path.name}\n\nstub body", 7)

    monkeypatch.setattr(ingest_mod, "_run_docling", _stub)
    return _stub


def test_unsupported_extension(tmp_path: Path, fake_docling) -> None:
    f = tmp_path / "card.pages"
    f.write_bytes(b"fake pages")
    result = ingest_document(f, store_root=tmp_path / "store")

    assert result.status == IngestionStatus.UNSUPPORTED
    assert not (tmp_path / "store").exists() or not any((tmp_path / "store").iterdir())


def test_missing_file(tmp_path: Path) -> None:
    result = ingest_document(tmp_path / "nope.pdf", store_root=tmp_path / "store")
    assert result.status == IngestionStatus.FAILED


def test_happy_path_creates_store(tmp_path: Path, fake_docling) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\nhello")
    store = tmp_path / "store"

    result = ingest_document(f, store_root=store)

    assert result.status == IngestionStatus.INGESTED
    assert result.document_id is not None
    assert result.storage_path is not None
    assert result.storage_path.is_dir()
    assert (result.storage_path / "metadata.json").is_file()
    assert (result.storage_path / "content.json").is_file()
    assert (result.storage_path / "content.md").is_file()
    assert (result.storage_path / "original.pdf").is_file()


def test_second_ingest_is_duplicate(tmp_path: Path, fake_docling) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\nhello")
    store = tmp_path / "store"

    first = ingest_document(f, store_root=store)
    second = ingest_document(f, store_root=store)

    assert first.status == IngestionStatus.INGESTED
    assert second.status == IngestionStatus.DUPLICATE
    assert second.document_id == first.document_id
    # No second storage dir.
    dirs = [p for p in store.iterdir() if p.is_dir() and not p.name.startswith(".tmp-")]
    assert len(dirs) == 1


def test_docling_failure_returns_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(path: Path):
        raise ingest_mod.UnsupportedFormatError("broken input")

    monkeypatch.setattr(ingest_mod, "_run_docling", boom)

    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\n")
    store = tmp_path / "store"
    result = ingest_document(f, store_root=store)

    assert result.status == IngestionStatus.UNSUPPORTED
    assert not store.exists() or not any(store.iterdir())


def test_degraded_doc_triggers_fallback_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Picture-wrapped OCR doc: quality=DEGRADED, md rebuilt from nested texts."""
    degraded_json = {
        "body": {"children": [{"$ref": "#/pictures/0"}]},
        "texts": [
            {"text": "Nom: MARTIN", "parent": {"$ref": "#/pictures/0"}},
            {"text": "Prenom: PIERRE", "parent": {"$ref": "#/pictures/0"}},
        ],
        "pictures": [{"children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]}],
    }
    empty_md = "<!-- image -->"

    def _stub(path: Path):
        return (degraded_json, empty_md, 3)

    monkeypatch.setattr(ingest_mod, "_run_docling", _stub)

    f = tmp_path / "passport.pdf"
    f.write_bytes(b"%PDF-1.4\n")
    store = tmp_path / "store"

    result = ingest_document(f, store_root=store)

    assert result.status == IngestionStatus.INGESTED
    assert result.metadata.extraction_quality == ExtractionQuality.DEGRADED
    md_on_disk = (result.storage_path / "content.md").read_text(encoding="utf-8")
    assert "MARTIN" in md_on_disk
    assert "PIERRE" in md_on_disk


def test_rich_doc_preserves_docling_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rich_json = {
        "body": {"children": [{"$ref": f"#/texts/{i}"} for i in range(5)]},
        "texts": [
            {"text": f"Paragraph {i}", "parent": {"$ref": "#/body"}} for i in range(5)
        ],
        "pictures": [],
    }
    original_md = "# Real markdown\n\nRich body content."

    def _stub(path: Path):
        return (rich_json, original_md, 3)

    monkeypatch.setattr(ingest_mod, "_run_docling", _stub)

    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\n")

    result = ingest_document(f, store_root=tmp_path / "store")

    assert result.metadata.extraction_quality == ExtractionQuality.RICH
    assert (result.storage_path / "content.md").read_text(encoding="utf-8") == original_md


@pytest.mark.integration
@pytest.mark.skipif(not RAW_DEMO.is_file(), reason=f"missing demo file: {RAW_DEMO}")
def test_integration_proposition_auto(tmp_path: Path) -> None:
    """End-to-end ingestion of the real demo file (no stubs)."""
    store = tmp_path / "store"
    result = ingest_document(RAW_DEMO, store_root=store)

    assert result.status == IngestionStatus.INGESTED, result.message
    assert result.metadata is not None
    assert result.metadata.mime_type == "application/pdf"
    assert result.metadata.size_bytes > 0
    assert result.metadata.processing_duration_ms >= 0

    # Second run → duplicate, idempotent.
    second = ingest_document(RAW_DEMO, store_root=store)
    assert second.status == IngestionStatus.DUPLICATE
    assert second.document_id == result.document_id

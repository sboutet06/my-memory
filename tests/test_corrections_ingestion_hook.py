"""End-to-end: ingestion hook writes corrections files when doubts exist."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from corrections.io import load_source_correction
from corrections.schemas import CorrectionStatus
from ingestion.ingest import ingest_document
from ingestion.models import ExtractionQuality, IngestionStatus


def _fake_docling_degraded(path):
    doc_json = {"texts": [], "pictures": [{"children": [{"$ref": "#/texts/0"}]}]}
    return doc_json, "<!-- image -->", 5


def _fake_docling_rich(path):
    doc_json = {
        "texts": [
            {"text": f"Body line {i}", "parent": {"$ref": "#/body"}}
            for i in range(5)
        ],
    }
    return doc_json, "Body text\n" * 5, 5


class TestIngestionHook:
    def test_clean_document_no_correction_file(self, tmp_path: Path) -> None:
        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        store = tmp_path / "store"
        corrections_root = tmp_path / "corrections"

        with patch("ingestion.ingest._run_docling", _fake_docling_rich), \
             patch("ingestion.ingest.detect_document_date", return_value="2026-01-01"):
            result = ingest_document(src, store_root=store, corrections_root=corrections_root)

        assert result.status == IngestionStatus.INGESTED
        # No doubts → no file written
        assert not (corrections_root / "source").exists() or \
               not any((corrections_root / "source").iterdir())

    def test_degraded_writes_correction(self, tmp_path: Path) -> None:
        src = tmp_path / "id.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        store = tmp_path / "store"
        corrections_root = tmp_path / "corrections"

        with patch("ingestion.ingest._run_docling", _fake_docling_degraded):
            result = ingest_document(src, store_root=store, corrections_root=corrections_root)

        assert result.status == IngestionStatus.INGESTED
        doc_id = result.document_id
        corr = load_source_correction(corrections_root, doc_id)
        assert corr is not None
        assert corr.status == CorrectionStatus.PENDING
        fields = {d.field for d in corr.doubts}
        # degraded quality should surface; missing date likely too
        assert "extraction_quality" in fields

    def test_unsupported_extension_writes_no_file_without_doc_id(self, tmp_path: Path) -> None:
        """Unsupported files have no doc_id — can't key a correction file."""
        src = tmp_path / "x.pages"
        src.write_bytes(b"fake")
        store = tmp_path / "store"
        corrections_root = tmp_path / "corrections"

        result = ingest_document(src, store_root=store, corrections_root=corrections_root)
        assert result.status == IngestionStatus.UNSUPPORTED
        # Nothing to key under — no correction file
        assert not (corrections_root / "source").exists() or \
               not any((corrections_root / "source").iterdir())

    def test_reingest_preserves_reviewed_status(self, tmp_path: Path) -> None:
        src = tmp_path / "id.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        store = tmp_path / "store"
        corrections_root = tmp_path / "corrections"

        with patch("ingestion.ingest._run_docling", _fake_docling_degraded):
            r1 = ingest_document(src, store_root=store, corrections_root=corrections_root)
        assert r1.status == IngestionStatus.INGESTED

        # User reviews + overrides
        from corrections.io import save_source_correction
        corr = load_source_correction(corrections_root, r1.document_id)
        corr.status = CorrectionStatus.REVIEWED
        corr.overrides["metadata"] = {"document_date": "2020-01-01"}
        save_source_correction(corrections_root, corr)

        # Re-ingest same file (duplicate path) — should not clobber user edits
        with patch("ingestion.ingest._run_docling", _fake_docling_degraded):
            r2 = ingest_document(src, store_root=store, corrections_root=corrections_root)
        assert r2.status == IngestionStatus.DUPLICATE

        post = load_source_correction(corrections_root, r1.document_id)
        assert post.status == CorrectionStatus.REVIEWED
        assert post.overrides["metadata"]["document_date"] == "2020-01-01"

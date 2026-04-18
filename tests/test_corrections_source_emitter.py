"""Source-layer doubts emitter."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from corrections.schemas import Confidence, SuggestedAction
from corrections.source_emitter import emit_doubts_for_metadata, emit_doubts_for_unsupported
from ingestion.models import DocumentMetadata, ExtractionQuality, SourceType


def _meta(**over) -> DocumentMetadata:
    defaults = dict(
        document_id="d-1",
        content_hash="h",
        original_filename="f.pdf",
        original_path="/tmp/f.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        ingested_at=datetime(2026, 4, 18),
        docling_version="2.88.0",
        processing_duration_ms=0,
        source_type=SourceType.FILESYSTEM,
        extraction_quality=ExtractionQuality.RICH,
        document_date=None,
    )
    defaults.update(over)
    return DocumentMetadata(**defaults)


class TestMetadataEmitter:
    def test_clean_rich_no_doubts(self) -> None:
        m = _meta(document_date="2026-01-01", extraction_quality=ExtractionQuality.RICH)
        assert emit_doubts_for_metadata(m) == []

    def test_missing_date_emits_doubt(self) -> None:
        doubts = emit_doubts_for_metadata(_meta(document_date=None))
        assert len(doubts) == 1
        assert doubts[0].field == "document_date"
        assert doubts[0].suggested_action == SuggestedAction.PROVIDE
        assert doubts[0].inferred_value is None

    def test_degraded_emits_quality_doubt(self) -> None:
        doubts = emit_doubts_for_metadata(_meta(
            document_date="2026-01-01",
            extraction_quality=ExtractionQuality.DEGRADED,
        ))
        fields = [d.field for d in doubts]
        assert "extraction_quality" in fields
        q = next(d for d in doubts if d.field == "extraction_quality")
        assert q.inferred_value == "degraded"
        assert q.suggested_action == SuggestedAction.REVIEW

    def test_empty_quality_emits_high_confidence_blocker(self) -> None:
        doubts = emit_doubts_for_metadata(_meta(
            document_date="2026-01-01",
            extraction_quality=ExtractionQuality.EMPTY,
        ))
        q = next(d for d in doubts if d.field == "extraction_quality")
        assert q.confidence == Confidence.HIGH

    def test_multiple_doubts(self) -> None:
        doubts = emit_doubts_for_metadata(_meta(
            document_date=None,
            extraction_quality=ExtractionQuality.DEGRADED,
        ))
        assert {d.field for d in doubts} == {"document_date", "extraction_quality"}


class TestUnsupportedEmitter:
    def test_unsupported_file_doubt(self) -> None:
        doubts = emit_doubts_for_unsupported(Path("/tmp/x.pages"))
        assert len(doubts) == 1
        assert doubts[0].field == "format"
        assert "pages" in doubts[0].inferred_value
        assert doubts[0].suggested_action == SuggestedAction.REPLACE

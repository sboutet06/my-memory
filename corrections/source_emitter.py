"""Source-layer doubts emitter — inspects ingestion artifacts for uncertainty."""
from __future__ import annotations

from pathlib import Path

from corrections.schemas import Confidence, Doubt, SuggestedAction
from ingestion.models import DocumentMetadata, ExtractionQuality


def emit_doubts_for_metadata(metadata: DocumentMetadata) -> list[Doubt]:
    """Inspect stored metadata; return doubts the user should review.

    Silent on clean documents. Surfaces:
      - missing document_date (heuristics found nothing usable)
      - degraded / empty extraction quality
    """
    out: list[Doubt] = []

    if metadata.document_date is None:
        out.append(Doubt(
            field="document_date",
            inferred_value=None,
            confidence=Confidence.LOW,
            rationale=(
                "No document_date detected. Heuristic scanned head and tail of "
                "the extracted text and found no usable issue/signing date."
            ),
            suggested_action=SuggestedAction.PROVIDE,
        ))

    if metadata.extraction_quality == ExtractionQuality.DEGRADED:
        out.append(Doubt(
            field="extraction_quality",
            inferred_value="degraded",
            confidence=Confidence.MEDIUM,
            rationale=(
                "Docling layout analyzer wrapped the page as a picture; OCR "
                "text was recovered via fallback renderer but carries no "
                "structural hierarchy. Verify content.md is usable."
            ),
            suggested_action=SuggestedAction.REVIEW,
        ))
    elif metadata.extraction_quality == ExtractionQuality.EMPTY:
        out.append(Doubt(
            field="extraction_quality",
            inferred_value="empty",
            confidence=Confidence.HIGH,
            rationale="Docling produced no usable text. Document likely unreadable.",
            suggested_action=SuggestedAction.REPLACE,
        ))

    return out


def emit_doubts_for_unsupported(path: Path) -> list[Doubt]:
    """Emit a doubt for files rejected at the extension-gate (e.g. .pages)."""
    ext = path.suffix.lower().lstrip(".")
    return [Doubt(
        field="format",
        inferred_value=f".{ext}",
        confidence=Confidence.HIGH,
        rationale=(
            f"Extension .{ext!s} not in Docling's supported set. "
            "Convert to PDF/DOCX and re-ingest, or add a pack-specific handler."
        ),
        suggested_action=SuggestedAction.REPLACE,
    )]

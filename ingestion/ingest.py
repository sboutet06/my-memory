"""Main orchestrator: `ingest_document` + supported-extension helper."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from corrections.io import (
    load_source_correction,
    merge_emitted_doubts,
    save_source_correction,
)
from corrections.source_emitter import emit_doubts_for_metadata
from ingestion.document_date import detect_document_date
from ingestion.metadata import build_metadata, compute_sha256, detect_mime_type
from ingestion.models import (
    DocumentMetadata,
    ExtractionQuality,
    IngestionResult,
    IngestionStatus,
)
from ingestion.quality import assess_quality, render_fallback_markdown
from ingestion.storage import find_duplicate, persist_document

logger = logging.getLogger(__name__)


class UnsupportedFormatError(RuntimeError):
    """Raised when Docling cannot process a file."""


DEFAULT_STORE_ROOT = Path("store")
DEFAULT_CORRECTIONS_ROOT = Path("corrections")

# Docling-supported extensions (mapped from `InputFormat`), plus common image types.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm",
    ".md", ".markdown", ".csv",
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp",
    ".xml", ".adoc", ".asciidoc",
})


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _run_docling(path: Path) -> tuple[dict, str, int]:
    """Invoke Docling; return (json_dict, markdown, duration_ms)."""
    # Imported lazily: Docling is slow to import.
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    start = time.perf_counter()
    try:
        result = converter.convert(path)
    except Exception as exc:
        raise UnsupportedFormatError(f"Docling cannot convert {path.name}: {exc}") from exc
    duration_ms = int((time.perf_counter() - start) * 1000)

    doc = result.document
    return doc.export_to_dict(), doc.export_to_markdown(), duration_ms


def _emit_source_corrections(
    corrections_root: Path,
    metadata: DocumentMetadata,
) -> None:
    """Write/merge a correction file iff the emitter produces doubts."""
    doubts = emit_doubts_for_metadata(metadata)
    if not doubts:
        return
    existing = load_source_correction(corrections_root, metadata.document_id)
    merged = merge_emitted_doubts(
        existing=existing,
        emitted=doubts,
        document_id=metadata.document_id,
        original_filename=metadata.original_filename,
    )
    save_source_correction(corrections_root, merged)
    logger.info(
        "Wrote %d doubt(s) for %s → %s/source/%s.yaml",
        len(doubts), metadata.document_id, corrections_root, metadata.document_id,
    )


def ingest_document(
    file_path: Path,
    *,
    store_root: Path = DEFAULT_STORE_ROOT,
    corrections_root: Path | None = None,
) -> IngestionResult:
    if corrections_root is None:
        # Sibling of store_root — keeps test tmpdirs self-contained.
        corrections_root = Path(store_root).parent / "corrections"
    """Ingest one file: hash → dedup → docling → persist.

    Idempotent: a second call with the same file returns `DUPLICATE` pointing at
    the existing document. Partial failures leave `store_root` untouched.
    """
    file_path = Path(file_path)
    if not file_path.is_file():
        return IngestionResult(
            status=IngestionStatus.FAILED,
            message=f"Not a regular file: {file_path}",
        )

    if not is_supported(file_path):
        logger.info("Unsupported extension for %s", file_path.name)
        return IngestionResult(
            status=IngestionStatus.UNSUPPORTED,
            message=f"Extension {file_path.suffix!r} not in supported set",
        )

    content_hash = compute_sha256(file_path)
    logger.debug("sha256(%s) = %s", file_path.name, content_hash)

    existing = find_duplicate(store_root, content_hash)
    if existing is not None:
        logger.info("Duplicate of %s (hash %s…)", existing.document_id, content_hash[:12])
        _emit_source_corrections(corrections_root, existing)
        return IngestionResult(
            status=IngestionStatus.DUPLICATE,
            document_id=existing.document_id,
            storage_path=store_root / existing.document_id,
            content_hash=content_hash,
            metadata=existing,
            message="Already ingested",
        )

    mime_type = detect_mime_type(file_path)

    try:
        docling_json, docling_md, duration_ms = _run_docling(file_path)
    except UnsupportedFormatError as exc:
        logger.error("Docling conversion failed: %s", exc)
        return IngestionResult(status=IngestionStatus.UNSUPPORTED, message=str(exc))

    quality = assess_quality(docling_json)
    if quality == ExtractionQuality.DEGRADED:
        recovered = render_fallback_markdown(docling_json)
        if recovered:
            docling_md = recovered

    document_date = detect_document_date(docling_md, file_path.name)

    metadata = build_metadata(
        source_path=file_path,
        content_hash=content_hash,
        mime_type=mime_type,
        processing_duration_ms=duration_ms,
        extraction_quality=quality,
        document_date=document_date,
    )

    try:
        storage_path = persist_document(
            store_root=store_root,
            metadata=metadata,
            docling_json=docling_json,
            docling_markdown=docling_md,
            source_path=file_path,
        )
    except Exception as exc:
        logger.exception("Persistence failed for %s", file_path.name)
        return IngestionResult(status=IngestionStatus.FAILED, message=str(exc))

    _emit_source_corrections(corrections_root, metadata)

    logger.info(
        "Ingested %s → %s (%d ms, %d bytes, quality=%s)",
        file_path.name, metadata.document_id, duration_ms, metadata.size_bytes,
        quality.value,
    )
    return IngestionResult(
        status=IngestionStatus.INGESTED,
        document_id=metadata.document_id,
        storage_path=storage_path,
        content_hash=content_hash,
        metadata=metadata,
    )

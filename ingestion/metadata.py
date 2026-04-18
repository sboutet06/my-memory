"""Hash, mime detection, metadata construction."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import uuid
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import puremagic

from ingestion.models import DocumentMetadata, ExtractionQuality, SourceType

logger = logging.getLogger(__name__)

_CHUNK = 1 << 20  # 1 MiB

# stdlib `mimetypes` omits some entries on macOS; register what we rely on.
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/markdown", ".markdown")


def compute_sha256(path: Path) -> str:
    """Stream SHA-256 of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


_OCTET = "application/octet-stream"


def detect_mime_type(path: Path) -> str:
    """Sniff mime from bytes (puremagic); fall back to stdlib by extension.

    puremagic returns `application/octet-stream` with low confidence when it
    cannot identify a file — treat that as "no answer" and try the extension.
    """
    try:
        guesses = puremagic.magic_file(str(path))
        if guesses:
            top = guesses[0]
            mime = getattr(top, "mime_type", None)
            confidence = getattr(top, "confidence", 0.0)
            if mime and mime != _OCTET and confidence >= 0.5:
                return mime
    except (puremagic.PureError, ValueError, OSError) as exc:
        logger.debug("puremagic failed on %s: %s", path, exc)

    guess, _ = mimetypes.guess_type(path.name)
    return guess or _OCTET


def docling_version() -> str:
    try:
        return version("docling")
    except PackageNotFoundError:
        return "unknown"


def build_metadata(
    *,
    source_path: Path,
    content_hash: str,
    mime_type: str,
    processing_duration_ms: int,
    extraction_quality: ExtractionQuality = ExtractionQuality.RICH,
    document_date: date | None = None,
    document_id: str | None = None,
    doc_context: list[str] | None = None,
) -> DocumentMetadata:
    """Assemble a `DocumentMetadata` from measured inputs."""
    return DocumentMetadata(
        document_id=document_id or str(uuid.uuid4()),
        content_hash=content_hash,
        original_filename=source_path.name,
        original_path=str(source_path.resolve()),
        mime_type=mime_type,
        size_bytes=source_path.stat().st_size,
        ingested_at=datetime.now(timezone.utc),
        docling_version=docling_version(),
        processing_duration_ms=processing_duration_ms,
        source_type=SourceType.FILESYSTEM,
        extraction_quality=extraction_quality,
        document_date=document_date,
        doc_context=doc_context or [],
    )

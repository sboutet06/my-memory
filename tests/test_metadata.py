"""Unit tests for hash, mime detection, and metadata assembly."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ingestion.metadata import (
    build_metadata,
    compute_sha256,
    detect_mime_type,
    docling_version,
)
from ingestion.models import SourceType


def test_compute_sha256_matches_hashlib(tmp_path: Path) -> None:
    payload = b"hello" * 10_000
    f = tmp_path / "a.bin"
    f.write_bytes(payload)

    assert compute_sha256(f) == hashlib.sha256(payload).hexdigest()


def test_compute_sha256_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    assert compute_sha256(f) == hashlib.sha256(b"").hexdigest()


def test_detect_mime_pdf_by_magic(tmp_path: Path) -> None:
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n")
    assert detect_mime_type(f) == "application/pdf"


def test_detect_mime_fallback_extension(tmp_path: Path) -> None:
    f = tmp_path / "note.md"
    f.write_text("# hi", encoding="utf-8")
    mime = detect_mime_type(f)
    # Either magic or stdlib mimetypes should land on markdown/plain text.
    assert mime in {"text/markdown", "text/x-markdown", "text/plain"}


def test_build_metadata_shape(tmp_path: Path) -> None:
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\n")
    meta = build_metadata(
        source_path=f,
        content_hash="a" * 64,
        mime_type="application/pdf",
        processing_duration_ms=42,
    )

    assert meta.original_filename == "doc.pdf"
    assert meta.original_path == str(f.resolve())
    assert meta.content_hash == "a" * 64
    assert meta.size_bytes == f.stat().st_size
    assert meta.processing_duration_ms == 42
    assert meta.source_type == SourceType.FILESYSTEM
    assert len(meta.document_id) == 36  # UUID v4
    assert meta.ingested_at.tzinfo is not None


def test_docling_version_resolves() -> None:
    v = docling_version()
    assert v != "unknown"
    assert v[0].isdigit()

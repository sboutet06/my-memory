"""Pydantic models for ingestion I/O and metadata schema."""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    FILESYSTEM = "filesystem"


class IngestionStatus(StrEnum):
    INGESTED = "ingested"
    DUPLICATE = "duplicate"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class ExtractionQuality(StrEnum):
    RICH = "rich"
    DEGRADED = "degraded"
    EMPTY = "empty"


class DocumentMetadata(BaseModel):
    """Metadata stored per ingested document."""

    document_id: str
    content_hash: str
    original_filename: str
    original_path: str
    mime_type: str
    size_bytes: int
    ingested_at: datetime
    docling_version: str
    processing_duration_ms: int = Field(ge=0)
    source_type: SourceType = SourceType.FILESYSTEM
    extraction_quality: ExtractionQuality = ExtractionQuality.RICH
    document_date: Optional[date] = None


class IngestionResult(BaseModel):
    """Result of an ingest call. `failed` / `unsupported` → no storage written."""

    status: IngestionStatus
    document_id: Optional[str] = None
    storage_path: Optional[Path] = None
    content_hash: Optional[str] = None
    message: Optional[str] = None
    metadata: Optional[DocumentMetadata] = None

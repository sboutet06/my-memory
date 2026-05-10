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
    # Re-ingest of the same source path with a new content_hash.
    # Phase 8b.1: prior version archived under versions/<n>/, current
    # pointer advanced.
    UPDATED = "updated"


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
    # Closed-vocabulary tags set at ingest time by the LLM classifier
    # (see ingestion/classifier.py). 1–3 tags, most relevant first.
    # Empty list = classifier not run or returned nothing.
    doc_context: list[str] = Field(default_factory=list)


class IngestionResult(BaseModel):
    """Result of an ingest call. `failed` / `unsupported` → no storage written."""

    status: IngestionStatus
    document_id: Optional[str] = None
    storage_path: Optional[Path] = None
    content_hash: Optional[str] = None
    message: Optional[str] = None
    metadata: Optional[DocumentMetadata] = None

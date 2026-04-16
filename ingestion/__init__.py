"""Document ingestion module (V0)."""
from ingestion.ingest import ingest_document
from ingestion.models import (
    DocumentMetadata,
    ExtractionQuality,
    IngestionResult,
    IngestionStatus,
    SourceType,
)

__all__ = [
    "ingest_document",
    "DocumentMetadata",
    "ExtractionQuality",
    "IngestionResult",
    "IngestionStatus",
    "SourceType",
]

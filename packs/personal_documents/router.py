"""Route an ingested document to its structured extractor.

V0 handles one doc kind (`bank_statement`). Add kinds here as extractors
arrive; detection signals should remain cheap (filename + first N chars
of markdown).
"""
from __future__ import annotations

import re
from typing import Optional

from packs.personal_documents.extractors.bank_statement import (
    extract_transactions,
)

_BANK_FILENAME_RE = re.compile(r"^(RLV|releve)", re.IGNORECASE)
_BANK_CONTENT_HINT = "RELEVE DE COMPTE"


def detect_doc_kind(metadata: dict, content_md: str) -> Optional[str]:
    """Classify the document into a known kind, or return None."""
    filename = metadata.get("original_filename", "") or ""
    if _BANK_FILENAME_RE.match(filename):
        return "bank_statement"
    head = (content_md or "")[:2000].upper()
    if _BANK_CONTENT_HINT in head:
        return "bank_statement"
    return None


def extract_structured(metadata: dict, content_md: str) -> Optional[dict]:
    """Run the matching extractor; return a {kind, ...} dict or None."""
    kind = detect_doc_kind(metadata, content_md)
    if kind is None:
        return None
    doc_id = metadata.get("document_id")
    if not doc_id:
        return None

    if kind == "bank_statement":
        transactions = extract_transactions(content_md, source_doc_id=doc_id)
        return {"kind": "bank_statement", "transactions": transactions}

    return None

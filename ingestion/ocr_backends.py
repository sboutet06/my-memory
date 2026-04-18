"""Alternate OCR backends.

Docling is the default (see `ingestion/ingest.py`). These wrappers are
invoked only when a source correction flags `ocr_backend: <name>` for a
specific document.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

KNOWN_BACKENDS: frozenset[str] = frozenset({"ocrmac"})


def _render_pdf_pages(pdf_path: Path, dpi: int = 200):
    """Render every PDF page to a PIL image list (deferred import)."""
    from pdf2image import convert_from_path  # local dep of ocrmac-style flow

    return convert_from_path(str(pdf_path), dpi=dpi)


def _ocrmac_recognize_image(image, language_preference: list[str]) -> list[str]:
    """Run Apple Vision OCR on a PIL image; return text lines (top-down)."""
    from ocrmac.ocrmac import OCR

    ocr = OCR(
        image,
        framework="vision",
        recognition_level="accurate",
        language_preference=language_preference,
    )
    results = ocr.recognize()
    # Results are (text, confidence, bbox). bbox y in normalized coords,
    # top-origin in ocrmac. Sort top-down, then left-to-right.
    lines = sorted(
        results,
        key=lambda r: (-(r[2][1]), r[2][0]) if r[2] else (0, 0),
    )
    return [text for text, _, _ in lines if text.strip()]


def run_ocrmac_on_pdf(
    pdf_path: Path,
    *,
    language_preference: Iterable[str] = ("fr-FR", "en-US"),
) -> str:
    """OCR every page of a PDF with Apple Vision; return concatenated markdown.

    Output is plain text paragraphs separated by blank lines between pages.
    """
    pages = _render_pdf_pages(pdf_path)
    languages = list(language_preference)
    out_pages: list[str] = []
    for idx, page_image in enumerate(pages):
        lines = _ocrmac_recognize_image(page_image, languages)
        if not lines:
            continue
        out_pages.append("\n".join(lines))
    return "\n\n".join(out_pages)

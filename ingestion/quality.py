"""Extraction-quality assessment and markdown recovery for degraded docs.

Docling's layout analyzer sometimes wraps an entire page as a `picture`
element (common on ID-type PDFs). OCR still runs and text is extracted,
but it lands as children of pictures — `export_to_markdown()` walks only
the top-level body hierarchy, so the emitted markdown is empty.

This module detects that case (`DEGRADED`) and provides a fallback
renderer that surfaces nested OCR text.
"""
from __future__ import annotations

from ingestion.models import ExtractionQuality

_BODY_REF = "#/body"
_RICH_TOP_LEVEL_TEXTS = 3


def _parent_ref(item: dict) -> str | None:
    parent = item.get("parent")
    if not isinstance(parent, dict):
        return None
    ref = parent.get("$ref")
    return ref if isinstance(ref, str) else None


def _top_level_text_count(doc: dict) -> int:
    texts = doc.get("texts", []) or []
    return sum(
        1
        for t in texts
        if isinstance(t, dict) and _parent_ref(t) == _BODY_REF and (t.get("text") or "").strip()
    )


def _nested_text_count(doc: dict) -> int:
    texts = doc.get("texts", []) or []
    return sum(
        1
        for t in texts
        if isinstance(t, dict)
        and _parent_ref(t) not in (None, _BODY_REF)
        and (t.get("text") or "").strip()
    )


def assess_quality(doc: dict) -> ExtractionQuality:
    """Classify a DoclingDocument dict by how much text landed at the body level.

    - RICH: enough top-level text that `export_to_markdown()` is usable.
    - DEGRADED: top-level body is thin but OCR text exists under pictures.
    - EMPTY: no text anywhere.
    """
    body = doc.get("body") or {}
    body_children = body.get("children") or []

    top_count = _top_level_text_count(doc)
    nested_count = _nested_text_count(doc)

    if top_count >= _RICH_TOP_LEVEL_TEXTS:
        return ExtractionQuality.RICH
    if top_count + nested_count == 0:
        return ExtractionQuality.EMPTY
    if not body_children:
        return ExtractionQuality.EMPTY
    return ExtractionQuality.DEGRADED


def _resolve_text_ref(doc: dict, ref: str) -> str | None:
    if not ref.startswith("#/texts/"):
        return None
    try:
        idx = int(ref.rsplit("/", 1)[-1])
    except ValueError:
        return None
    texts = doc.get("texts") or []
    if 0 <= idx < len(texts):
        item = texts[idx]
        if isinstance(item, dict):
            return (item.get("text") or "").strip() or None
    return None


def render_fallback_markdown(doc: dict) -> str:
    """Rebuild a readable markdown rendering by walking picture children.

    Only used when `assess_quality` returns DEGRADED. Emits a `## Picture N`
    heading per picture and one paragraph per non-empty child text ref, in
    document order.
    """
    pictures = doc.get("pictures") or []
    blocks: list[str] = []

    for idx, picture in enumerate(pictures):
        if not isinstance(picture, dict):
            continue
        children = picture.get("children") or []
        lines: list[str] = []
        for child in children:
            if not isinstance(child, dict):
                continue
            ref = child.get("$ref")
            if not isinstance(ref, str):
                continue
            text = _resolve_text_ref(doc, ref)
            if text:
                lines.append(text)
        if lines:
            blocks.append(f"## Picture {idx + 1}\n\n" + "\n\n".join(lines))

    return "\n\n".join(blocks)

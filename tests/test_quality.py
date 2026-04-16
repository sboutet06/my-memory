"""Unit tests for extraction quality assessment and markdown recovery."""
from __future__ import annotations

from ingestion.models import ExtractionQuality
from ingestion.quality import assess_quality, render_fallback_markdown


def _doc(body_children: list[dict], texts: list[dict], pictures: list[dict]) -> dict:
    return {
        "body": {"children": body_children},
        "texts": texts,
        "pictures": pictures,
    }


def test_rich_when_top_level_texts_dominant() -> None:
    body_kids = [{"$ref": f"#/texts/{i}"} for i in range(5)]
    texts = [
        {"text": f"paragraph {i}", "parent": {"$ref": "#/body"}} for i in range(5)
    ]
    assert assess_quality(_doc(body_kids, texts, [])) == ExtractionQuality.RICH


def test_degraded_when_texts_nested_under_pictures() -> None:
    body_kids = [{"$ref": "#/pictures/0"}, {"$ref": "#/pictures/1"}]
    texts = [
        {"text": "Nom: MARTIN", "parent": {"$ref": "#/pictures/0"}},
        {"text": "Prenom: PIERRE", "parent": {"$ref": "#/pictures/0"}},
        {"text": "Date: 01/01/2000", "parent": {"$ref": "#/pictures/1"}},
    ]
    pictures = [
        {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]},
        {"children": [{"$ref": "#/texts/2"}]},
    ]
    assert assess_quality(_doc(body_kids, texts, pictures)) == ExtractionQuality.DEGRADED


def test_empty_when_no_texts_anywhere() -> None:
    body_kids = [{"$ref": "#/pictures/0"}]
    pictures = [{"children": []}]
    assert assess_quality(_doc(body_kids, [], pictures)) == ExtractionQuality.EMPTY


def test_empty_when_body_is_empty() -> None:
    assert assess_quality(_doc([], [], [])) == ExtractionQuality.EMPTY


def test_rich_boundary_exactly_threshold() -> None:
    # Threshold is 3 top-level texts (inclusive).
    body_kids = [{"$ref": f"#/texts/{i}"} for i in range(3)]
    texts = [{"text": "x", "parent": {"$ref": "#/body"}} for _ in range(3)]
    assert assess_quality(_doc(body_kids, texts, [])) == ExtractionQuality.RICH


def test_degraded_below_threshold_with_nested() -> None:
    body_kids = [
        {"$ref": "#/texts/0"},
        {"$ref": "#/pictures/0"},
    ]
    texts = [
        {"text": "header", "parent": {"$ref": "#/body"}},
        {"text": "buried", "parent": {"$ref": "#/pictures/0"}},
    ]
    pictures = [{"children": [{"$ref": "#/texts/1"}]}]
    assert assess_quality(_doc(body_kids, texts, pictures)) == ExtractionQuality.DEGRADED


def test_render_fallback_extracts_nested_texts_in_order() -> None:
    texts = [
        {"text": "Nom: MARTIN", "parent": {"$ref": "#/pictures/0"}},
        {"text": "Prenom: PIERRE", "parent": {"$ref": "#/pictures/0"}},
        {"text": "Date: 01/01/2000", "parent": {"$ref": "#/pictures/1"}},
    ]
    pictures = [
        {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]},
        {"children": [{"$ref": "#/texts/2"}]},
    ]
    md = render_fallback_markdown(_doc([], texts, pictures))

    assert "Nom: MARTIN" in md
    assert "Prenom: PIERRE" in md
    assert "Date: 01/01/2000" in md
    # Order preserved per picture traversal.
    assert md.index("MARTIN") < md.index("PIERRE") < md.index("01/01/2000")


def test_render_fallback_skips_empty_texts() -> None:
    texts = [
        {"text": "real", "parent": {"$ref": "#/pictures/0"}},
        {"text": "   ", "parent": {"$ref": "#/pictures/0"}},
        {"text": "", "parent": {"$ref": "#/pictures/0"}},
    ]
    pictures = [{"children": [{"$ref": f"#/texts/{i}"} for i in range(3)]}]
    md = render_fallback_markdown(_doc([], texts, pictures))

    assert "real" in md
    assert md.count("\n\n") <= 2  # No blank-only entries inflating the doc.

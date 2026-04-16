"""Unit tests for entity-type enforcement."""
from __future__ import annotations

from extraction.taxonomy import normalize_entity_type


ALLOWED = ["person", "organization", "location", "date", "concept"]


def test_allowed_type_passes_through() -> None:
    node = {"entity_type": "person"}
    normalize_entity_type(node, ALLOWED)
    assert node["entity_type"] == "person"


def test_disallowed_type_remaps_to_fallback() -> None:
    node = {"entity_type": "artifact"}
    normalize_entity_type(node, ALLOWED, fallback="concept")
    assert node["entity_type"] == "concept"


def test_case_insensitive_match() -> None:
    node = {"entity_type": "Person"}
    normalize_entity_type(node, ALLOWED)
    assert node["entity_type"] == "person"  # canonicalized to lowercase


def test_missing_type_is_replaced_with_fallback() -> None:
    node: dict = {}
    normalize_entity_type(node, ALLOWED, fallback="concept")
    assert node["entity_type"] == "concept"


def test_null_type_is_replaced_with_fallback() -> None:
    node = {"entity_type": None}
    normalize_entity_type(node, ALLOWED, fallback="concept")
    assert node["entity_type"] == "concept"


def test_returns_was_remapped_flag() -> None:
    ok = normalize_entity_type({"entity_type": "person"}, ALLOWED)
    remapped = normalize_entity_type({"entity_type": "artifact"}, ALLOWED)
    assert ok is False
    assert remapped is True

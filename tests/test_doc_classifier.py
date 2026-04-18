"""Doc classifier — pure JSON parsing + tag validation."""
from __future__ import annotations

import pytest

from ingestion.classifier import (
    DOC_CONTEXT_TAGS,
    parse_classifier_response,
)


class TestParseClassifierResponse:
    def test_well_formed(self) -> None:
        raw = '{"tags": ["healthcare", "family"], "rationale": "medical cert for minor"}'
        tags, rationale = parse_classifier_response(raw)
        assert tags == ["healthcare", "family"]
        assert rationale == "medical cert for minor"

    def test_with_code_fences(self) -> None:
        raw = '```json\n{"tags": ["work"], "rationale": "payslip"}\n```'
        tags, rationale = parse_classifier_response(raw)
        assert tags == ["work"]

    def test_drops_unknown_tags(self) -> None:
        raw = '{"tags": ["work", "gibberish", "finance"], "rationale": "x"}'
        tags, _ = parse_classifier_response(raw)
        assert tags == ["work", "finance"]

    def test_deduplicates_tags(self) -> None:
        raw = '{"tags": ["work", "work", "finance"], "rationale": "x"}'
        tags, _ = parse_classifier_response(raw)
        assert tags == ["work", "finance"]

    def test_caps_at_three_tags(self) -> None:
        raw = (
            '{"tags": ["work", "finance", "family", "legal", "travel"], '
            '"rationale": "many"}'
        )
        tags, _ = parse_classifier_response(raw)
        assert len(tags) <= 3

    def test_empty_tags_becomes_other(self) -> None:
        raw = '{"tags": [], "rationale": "nothing"}'
        tags, _ = parse_classifier_response(raw)
        assert tags == ["other"]

    def test_invalid_json_returns_other(self) -> None:
        raw = "not json at all"
        tags, rationale = parse_classifier_response(raw)
        assert tags == ["other"]
        assert "parse" in rationale.lower() or "invalid" in rationale.lower()

    def test_missing_tags_field(self) -> None:
        raw = '{"rationale": "just rationale"}'
        tags, _ = parse_classifier_response(raw)
        assert tags == ["other"]

    def test_tag_vocab_stable(self) -> None:
        # Sanity — guard against accidental removal of a core tag.
        for t in ("work", "healthcare", "finance", "property", "vehicle",
                  "identity", "family", "legal", "education", "travel",
                  "food", "administrative", "other"):
            assert t in DOC_CONTEXT_TAGS

    def test_lowercase_normalization(self) -> None:
        raw = '{"tags": ["WORK", "Finance"], "rationale": "x"}'
        tags, _ = parse_classifier_response(raw)
        assert tags == ["work", "finance"]

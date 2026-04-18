"""Schemas for the corrections framework (Phase 3.5)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from corrections.schemas import (
    Confidence,
    CorrectionStatus,
    Doubt,
    SourceCorrection,
    SuggestedAction,
)


class TestDoubt:
    def test_minimal(self) -> None:
        d = Doubt(
            field="document_date",
            inferred_value=None,
            confidence=Confidence.LOW,
            rationale="No date found in head/tail scan.",
            suggested_action=SuggestedAction.PROVIDE,
        )
        assert d.field == "document_date"
        assert d.inferred_value is None
        assert d.confidence == Confidence.LOW

    def test_inferred_value_accepts_any_scalar(self) -> None:
        Doubt(
            field="f", inferred_value="2026-01-01",
            confidence=Confidence.MEDIUM, rationale="r",
            suggested_action=SuggestedAction.CONFIRM,
        )
        Doubt(
            field="f", inferred_value=42,
            confidence=Confidence.HIGH, rationale="r",
            suggested_action=SuggestedAction.CONFIRM,
        )

    def test_rationale_required(self) -> None:
        with pytest.raises(ValidationError):
            Doubt(
                field="f", inferred_value=None,
                confidence=Confidence.LOW, rationale="",
                suggested_action=SuggestedAction.CONFIRM,
            )


class TestSourceCorrection:
    def _doc(self, **kw):
        defaults = dict(
            document_id="abc-123",
            original_filename="x.pdf",
            status=CorrectionStatus.PENDING,
            doubts=[],
            overrides={"metadata": {}, "content_replacements": [], "tags": []},
        )
        defaults.update(kw)
        return SourceCorrection(**defaults)

    def test_empty_overrides_ok(self) -> None:
        c = self._doc()
        assert c.status == CorrectionStatus.PENDING
        assert c.overrides["metadata"] == {}

    def test_replaced_by_optional(self) -> None:
        c = self._doc(replaced_by="other-doc-id")
        assert c.replaced_by == "other-doc-id"

    def test_metadata_override_keys_allowed(self) -> None:
        c = self._doc(overrides={
            "metadata": {"document_date": "2016-05-13"},
            "content_replacements": [{"find": "CEUNE", "replace": "CEDRES"}],
            "tags": ["obsolete"],
        })
        assert c.overrides["metadata"]["document_date"] == "2016-05-13"
        assert c.overrides["content_replacements"][0]["find"] == "CEUNE"

    def test_status_roundtrip_enum_values(self) -> None:
        assert CorrectionStatus.PENDING.value == "pending"
        assert CorrectionStatus.REVIEWED.value == "reviewed"

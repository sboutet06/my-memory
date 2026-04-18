"""YAML round-trip + idempotent merge for corrections files."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from corrections.io import (
    correction_path,
    load_source_correction,
    merge_emitted_doubts,
    save_source_correction,
)
from corrections.schemas import (
    Confidence,
    CorrectionStatus,
    Doubt,
    SourceCorrection,
    SuggestedAction,
)


def _doubt(field: str = "document_date", val=None) -> Doubt:
    return Doubt(
        field=field,
        inferred_value=val,
        confidence=Confidence.MEDIUM,
        rationale="test rationale",
        suggested_action=SuggestedAction.CONFIRM,
    )


def _correction(doc_id: str = "doc-1", doubts=None, overrides=None) -> SourceCorrection:
    return SourceCorrection(
        document_id=doc_id,
        original_filename=f"{doc_id}.pdf",
        status=CorrectionStatus.PENDING,
        doubts=doubts or [],
        overrides=overrides or {},
    )


class TestRoundtrip:
    def test_save_and_load(self, tmp_path: Path) -> None:
        c = _correction(doubts=[_doubt()])
        save_source_correction(tmp_path, c)
        loaded = load_source_correction(tmp_path, c.document_id)
        assert loaded is not None
        assert loaded.document_id == c.document_id
        assert len(loaded.doubts) == 1
        assert loaded.doubts[0].field == "document_date"

    def test_path_layout(self, tmp_path: Path) -> None:
        p = correction_path(tmp_path, "doc-xyz")
        assert p == tmp_path / "source" / "doc-xyz.yaml"

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        assert load_source_correction(tmp_path, "nope") is None

    def test_yaml_is_human_readable(self, tmp_path: Path) -> None:
        c = _correction(doubts=[_doubt("document_date", "2016-05-13")])
        save_source_correction(tmp_path, c)
        raw = correction_path(tmp_path, c.document_id).read_text()
        # Top-level keys appear unquoted, in fixed order.
        assert raw.splitlines()[0].startswith("document_id:")
        data = yaml.safe_load(raw)
        assert data["status"] == "pending"
        assert data["doubts"][0]["inferred_value"] == "2016-05-13"


class TestMergeIdempotent:
    def test_empty_existing_accepts_all_new(self) -> None:
        merged = merge_emitted_doubts(existing=None, emitted=[_doubt("a"), _doubt("b")],
                                      document_id="d", original_filename="d.pdf")
        assert [d.field for d in merged.doubts] == ["a", "b"]
        assert merged.status == CorrectionStatus.PENDING

    def test_reemit_preserves_user_overrides(self) -> None:
        existing = _correction(overrides={"metadata": {"document_date": "2016-05-13"}})
        existing.status = CorrectionStatus.REVIEWED
        merged = merge_emitted_doubts(
            existing=existing,
            emitted=[_doubt("document_date", "2017-01-01")],
            document_id=existing.document_id,
            original_filename=existing.original_filename,
        )
        # User-edited overrides survive.
        assert merged.overrides["metadata"]["document_date"] == "2016-05-13"
        # Reviewed stays reviewed even if new doubts emitted.
        assert merged.status == CorrectionStatus.REVIEWED

    def test_reemit_replaces_pending_doubts(self) -> None:
        existing = _correction(doubts=[_doubt("old_field")])
        merged = merge_emitted_doubts(
            existing=existing,
            emitted=[_doubt("new_field")],
            document_id=existing.document_id,
            original_filename=existing.original_filename,
        )
        assert [d.field for d in merged.doubts] == ["new_field"]

    def test_idempotent_double_merge(self) -> None:
        e = [_doubt("a"), _doubt("b")]
        m1 = merge_emitted_doubts(None, e, document_id="d", original_filename="d.pdf")
        m2 = merge_emitted_doubts(m1, e, document_id="d", original_filename="d.pdf")
        assert m1.model_dump() == m2.model_dump()

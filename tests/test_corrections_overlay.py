"""Overlay applier: apply a SourceCorrection on top of stored metadata/content."""
from __future__ import annotations

from corrections.overlay import apply_content_overlay, apply_metadata_overlay
from corrections.schemas import CorrectionStatus, SourceCorrection


def _corr(**over) -> SourceCorrection:
    return SourceCorrection(
        document_id="d",
        original_filename="d.pdf",
        status=CorrectionStatus.PENDING,
        overrides=over,
    )


class TestMetadataOverlay:
    def test_none_is_noop(self) -> None:
        meta = {"document_date": None, "tags": []}
        out = apply_metadata_overlay(meta, None)
        assert out == meta
        assert out is not meta  # copy

    def test_empty_overrides_noop(self) -> None:
        meta = {"document_date": None}
        out = apply_metadata_overlay(meta, _corr())
        assert out == meta

    def test_metadata_override_wins(self) -> None:
        meta = {"document_date": None, "extraction_quality": "degraded"}
        c = _corr(metadata={"document_date": "2016-05-13"})
        out = apply_metadata_overlay(meta, c)
        assert out["document_date"] == "2016-05-13"
        assert out["extraction_quality"] == "degraded"

    def test_tags_merge(self) -> None:
        meta = {"tags": ["x"]}
        c = _corr(tags=["obsolete"])
        out = apply_metadata_overlay(meta, c)
        assert set(out["tags"]) == {"x", "obsolete"}

    def test_replaced_by_surfaces_on_metadata(self) -> None:
        meta = {}
        c = SourceCorrection(
            document_id="d", original_filename="d.pdf",
            status=CorrectionStatus.REVIEWED, replaced_by="new-id",
        )
        out = apply_metadata_overlay(meta, c)
        assert out["replaced_by"] == "new-id"


class TestContentOverlay:
    def test_no_replacements(self) -> None:
        assert apply_content_overlay("hello world", None) == "hello world"
        assert apply_content_overlay("hello world", _corr()) == "hello world"

    def test_literal_replace(self) -> None:
        c = _corr(content_replacements=[{"find": "CEUNE", "replace": "CEDRES"}])
        out = apply_content_overlay("born at CEUNE village", c)
        assert out == "born at CEDRES village"

    def test_multiple_replacements_ordered(self) -> None:
        c = _corr(content_replacements=[
            {"find": "foo", "replace": "bar"},
            {"find": "bar", "replace": "baz"},
        ])
        # first sub → "bar world", then second → "baz world"
        assert apply_content_overlay("foo world", c) == "baz world"

    def test_missing_find_ignored(self) -> None:
        c = _corr(content_replacements=[{"find": "zzz", "replace": "qqq"}])
        assert apply_content_overlay("hello", c) == "hello"

"""Content-overlay resolves ocr_backend + content_md_override_path."""
from __future__ import annotations

from pathlib import Path

from corrections.io import save_source_correction
from corrections.overlay import apply_content_overlay, resolve_content
from corrections.schemas import CorrectionStatus, SourceCorrection


def _corr(**over) -> SourceCorrection:
    return SourceCorrection(
        document_id="doc-1",
        original_filename="doc-1.pdf",
        status=CorrectionStatus.PENDING,
        overrides=over,
    )


class TestResolveContent:
    def test_no_correction_returns_original(self, tmp_path: Path) -> None:
        assert resolve_content("original body", None, tmp_path) == "original body"

    def test_no_override_returns_original(self, tmp_path: Path) -> None:
        assert resolve_content(
            "original", _corr(), tmp_path,
        ) == "original"

    def test_content_md_override_path_replaces_body(self, tmp_path: Path) -> None:
        overlay = tmp_path / "overlay.md"
        overlay.write_text("fully re-OCR'd content\n")
        out = resolve_content(
            "original",
            _corr(content_md_override_path="overlay.md"),
            tmp_path,
        )
        assert out == "fully re-OCR'd content\n"

    def test_missing_overlay_file_falls_back_to_original(self, tmp_path: Path) -> None:
        out = resolve_content(
            "original",
            _corr(content_md_override_path="nope.md"),
            tmp_path,
        )
        assert out == "original"

    def test_content_replacements_still_apply_after_override(
        self, tmp_path: Path,
    ) -> None:
        overlay = tmp_path / "ov.md"
        overlay.write_text("Born at CEUNE village")
        out = resolve_content(
            "ignored",
            _corr(
                content_md_override_path="ov.md",
                content_replacements=[{"find": "CEUNE", "replace": "CEDRES"}],
            ),
            tmp_path,
        )
        assert out == "Born at CEDRES village"


class TestSchemaOCRField:
    def test_ocr_backend_field_optional(self, tmp_path: Path) -> None:
        c = SourceCorrection(
            document_id="d", original_filename="d.pdf",
            overrides={"ocr_backend": "ocrmac"},
        )
        assert c.overrides["ocr_backend"] == "ocrmac"

    def test_ocr_backend_defaults_to_none(self) -> None:
        c = SourceCorrection(document_id="d", original_filename="d.pdf")
        assert c.overrides["ocr_backend"] is None

    def test_yaml_roundtrip_with_ocr_fields(self, tmp_path: Path) -> None:
        c = SourceCorrection(
            document_id="d", original_filename="d.pdf",
            overrides={
                "ocr_backend": "ocrmac",
                "content_md_override_path": "d.md",
            },
        )
        save_source_correction(tmp_path, c)
        raw = (tmp_path / "source" / "d.yaml").read_text()
        assert "ocr_backend" in raw
        assert "content_md_override_path" in raw
        # Inline hints present
        assert "ocrmac" in raw

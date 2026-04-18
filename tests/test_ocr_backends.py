"""OCR backend dispatcher + `ocrmac` wrapper."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from ingestion.ocr_backends import run_ocrmac_on_pdf, KNOWN_BACKENDS


class TestRegistry:
    def test_ocrmac_in_backends(self) -> None:
        assert "ocrmac" in KNOWN_BACKENDS


class TestRunOCRmacOnPDF:
    @patch("ingestion.ocr_backends._ocrmac_recognize_image")
    @patch("ingestion.ocr_backends._render_pdf_pages")
    def test_concatenates_pages(self, mock_render, mock_recognize, tmp_path: Path) -> None:
        p = tmp_path / "x.pdf"
        p.write_bytes(b"%PDF")
        # Two fake pages, each returning OCR lines.
        fake_img1 = MagicMock()
        fake_img2 = MagicMock()
        mock_render.return_value = [fake_img1, fake_img2]
        mock_recognize.side_effect = [
            ["Line 1 page 1", "Line 2 page 1"],
            ["Line 1 page 2"],
        ]
        text = run_ocrmac_on_pdf(p, language_preference=["fr-FR"])
        assert "Line 1 page 1" in text
        assert "Line 2 page 1" in text
        assert "Line 1 page 2" in text
        # Pages separated by a blank line.
        assert "\n\n" in text

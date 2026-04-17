"""Unit tests for pure helpers in `extraction.graph`."""
from __future__ import annotations

from extraction.graph import _prepend_date_header


def test_no_date_returns_text_unchanged() -> None:
    assert _prepend_date_header("body", None) == "body"
    assert _prepend_date_header("body", "") == "body"


def test_date_is_prepended_as_header() -> None:
    out = _prepend_date_header("body text", "2015-06-12")
    assert out.startswith("[DOCUMENT DATE: 2015-06-12]")
    assert "body text" in out


def test_header_separated_from_body_by_blank_line() -> None:
    out = _prepend_date_header("body", "2020-01-01")
    assert "\n\nbody" in out

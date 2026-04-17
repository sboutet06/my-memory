"""Unit tests for document-date heuristic (pure, offline)."""
from __future__ import annotations

from datetime import date

import pytest

from ingestion.document_date import detect_document_date


def test_iso_date_in_body() -> None:
    text = "Report generated on 2019-07-15 by system."
    assert detect_document_date(text, "x.pdf") == date(2019, 7, 15)


def test_french_slash_date_in_body() -> None:
    text = "Facture émise le 12/06/2015 à Paris."
    assert detect_document_date(text, "x.pdf") == date(2015, 6, 12)


def test_keyword_anchored_date_wins_over_random_later_date() -> None:
    # A random date appears early, but the keyword-anchored one is the issue date.
    text = (
        "Référence de transaction : 01/01/2000 pour identification.\n\n"
        "Émise le 03/02/2013 à Nice."
    )
    assert detect_document_date(text, "x.pdf") == date(2013, 2, 3)


def test_filename_yyyymmdd_fallback() -> None:
    text = "No dates anywhere in this body."
    assert detect_document_date(text, "telereglement_IR_20130203_095407.pdf") == date(
        2013, 2, 3
    )


def test_filename_dashed_iso() -> None:
    text = ""
    assert detect_document_date(text, "report_2024-11-05_v2.pdf") == date(2024, 11, 5)


def test_no_date_found_returns_none() -> None:
    text = "Content with no date references whatsoever."
    assert detect_document_date(text, "random.pdf") is None


def test_invalid_date_rejected() -> None:
    text = "Ref 99/99/9999 is not a date."
    assert detect_document_date(text, "x.pdf") is None


def test_ignores_unreasonable_years() -> None:
    """Years < 1900 or > 2100 are almost certainly noise (e.g. IDs, page counts)."""
    text = "Invoice #28/04/1234 for customer."
    assert detect_document_date(text, "x.pdf") is None


def test_dot_separator_french_or_german() -> None:
    text = "Signé le 22.04.2016 par le notaire."
    assert detect_document_date(text, "x.pdf") == date(2016, 4, 22)


def test_body_takes_priority_over_filename() -> None:
    text = "Émise le 15/03/2020 à Lyon."
    # Filename says something different.
    assert detect_document_date(text, "old_20100101.pdf") == date(2020, 3, 15)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Date: 2021-02-28", date(2021, 2, 28)),
        ("Rédigé en 2019.", None),  # year-only is too ambiguous for V0
    ],
)
def test_parametrized_cases(text: str, expected: date | None) -> None:
    assert detect_document_date(text, "x.pdf") == expected


def test_rejects_birthdate() -> None:
    """`né le 24/11/1977` is a birthdate, not a document date."""
    text = (
        "SITUATION DU FOYER FISCAL\n"
        "Monsieur : SEBASTIEN JEAN CHRISTOPHE BOUTET né le 24/11/1977 - BLOIS (41)\n"
        "Madame : MYLENE ELKAIM née le 25/04/1979 - NICE (06)\n"
    )
    # No other date present → None is the honest answer.
    assert detect_document_date(text, "x.pdf") is None


def test_rejects_validity_window_depuis_le() -> None:
    """Driving-license valid-from segments must not masquerade as doc dates."""
    text = "CIRCA 4\nDEPUIS LE 01/03/1996"
    assert detect_document_date(text, "x.pdf") is None


def test_birthdate_rejected_but_real_issue_date_picked() -> None:
    """Birthdate should be skipped; a subsequent issue-keyworded date wins."""
    text = (
        "BOUTET né le 24/11/1977 à BLOIS.\n"
        "Émise le 12/06/2015 à Paris.\n"
    )
    assert detect_document_date(text, "x.pdf") == date(2015, 6, 12)


def test_only_scans_first_window() -> None:
    """Dates deep in a huge doc shouldn't dominate; the header is what matters."""
    # 10000 chars of noise, then a date.
    padding = "lorem ipsum " * 1000
    text = padding + "Émise le 03/02/2013."
    # Should not find that date (out of window). No other date present.
    assert detect_document_date(text, "x.pdf") is None

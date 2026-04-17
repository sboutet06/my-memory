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


# -- French textual dates --------------------------------------------------

def test_french_textual_date_with_month_name() -> None:
    text = "Fait à Fayence le 22 avril 2016 par le notaire."
    assert detect_document_date(text, "x.pdf") == date(2016, 4, 22)


def test_french_textual_date_accented_month() -> None:
    text = "Signé le 5 août 2008 à Nice."
    assert detect_document_date(text, "x.pdf") == date(2008, 8, 5)


def test_french_textual_date_unaccented_variant() -> None:
    text = "Document emis le 1 fevrier 2019."
    assert detect_document_date(text, "x.pdf") == date(2019, 2, 1)


def test_french_textual_birthdate_still_rejected() -> None:
    """`né le 24 novembre 1977` in textual form must also be rejected."""
    text = "BOUTET né le 24 novembre 1977 à Blois."
    assert detect_document_date(text, "x.pdf") is None


# -- Max-date fallback (most-recent wins when no keyword anchors) ----------

def test_undated_doc_picks_latest_nonbirthday_date() -> None:
    """A contract body with scattered past-event dates: latest = issue date."""
    text = (
        "Les parties se sont rencontrées le 13 janvier 2006. Le diagnostic "
        "amiante date du 22 avril 2016. Le 30 juin 2016 le compromis a été "
        "régularisé."
    )
    assert detect_document_date(text, "x.pdf") == date(2016, 6, 30)


def test_undated_doc_ignores_future_years_from_noise() -> None:
    """Year-only year noise like '2019' must not slip through (no day+month)."""
    text = "Rédigé en 2019. Le 15 mars 2016 quelque chose a eu lieu."
    assert detect_document_date(text, "x.pdf") == date(2016, 3, 15)


def test_ignores_date_buried_in_the_middle() -> None:
    """Dates deep in the body (outside head + tail windows) must be ignored."""
    # 7000 chars padding, date in the middle, 7000 more chars padding.
    pad_front = "lorem ipsum " * 700
    pad_back = "dolor sit amet " * 700
    text = pad_front + "Émise le 03/02/2013." + pad_back
    assert detect_document_date(text, "x.pdf") is None


def test_keyword_anchored_date_in_footer_is_found() -> None:
    """Legal docs sign at the bottom: `FAIT à X Le Y`."""
    header = "Compromis de vente entre parties. " * 100  # ~3500 chars
    middle = "Past event details. " * 200  # noise
    footer = "FAIT à CHATEAUNEUF Le 13 mai 2016\nEn un seul exemplaire."
    text = header + middle + footer
    assert detect_document_date(text, "x.pdf") == date(2016, 5, 13)


def test_marriage_date_is_disqualified() -> None:
    """Marriage date must not be picked as document date."""
    text = "Mariés à la mairie de MONTAUROUX le 5 juillet 2008."
    assert detect_document_date(text, "x.pdf") is None

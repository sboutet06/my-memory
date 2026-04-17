"""Unit tests for temporal annotation (date-prefix on node/edge descriptions)."""
from __future__ import annotations

from datetime import date

from extraction.temporal import (
    SOURCED_PREFIX,
    annotate_with_sourced_dates,
    build_sourced_prefix,
    has_sourced_prefix,
)


def _doc_dates() -> dict[str, date]:
    return {
        "111": date(2015, 6, 1),
        "222": date(2020, 3, 14),
        "333": date(2026, 1, 5),
    }


def test_build_prefix_single_date() -> None:
    assert build_sourced_prefix([date(2015, 6, 1)]) == "[sourced: 2015-06-01] "


def test_build_prefix_multiple_dates_sorted_dedup() -> None:
    dates = [date(2020, 3, 14), date(2015, 6, 1), date(2020, 3, 14)]
    assert build_sourced_prefix(dates) == "[sourced: 2015-06-01, 2020-03-14] "


def test_build_prefix_empty_returns_empty_string() -> None:
    assert build_sourced_prefix([]) == ""


def test_annotate_adds_prefix_when_absent() -> None:
    rec = {"description": "Alice lives somewhere.", "document_ids": "111"}
    mutated = annotate_with_sourced_dates(rec, _doc_dates())
    assert mutated is True
    assert rec["description"].startswith(SOURCED_PREFIX)
    assert "2015-06-01" in rec["description"]
    assert "Alice lives somewhere." in rec["description"]


def test_annotate_is_idempotent() -> None:
    rec = {"description": "Alice lives somewhere.", "document_ids": "111"}
    annotate_with_sourced_dates(rec, _doc_dates())
    before = rec["description"]
    mutated_again = annotate_with_sourced_dates(rec, _doc_dates())
    assert mutated_again is False
    assert rec["description"] == before


def test_annotate_uses_sep_for_multi_docs() -> None:
    SEP = "<SEP>"
    rec = {"description": "x", "document_ids": f"222{SEP}111"}
    annotate_with_sourced_dates(rec, _doc_dates())
    # Sorted ascending; earliest first.
    assert "2015-06-01, 2020-03-14" in rec["description"]


def test_annotate_no_document_ids_noop() -> None:
    rec = {"description": "x"}
    mutated = annotate_with_sourced_dates(rec, _doc_dates())
    assert mutated is False
    assert rec["description"] == "x"


def test_annotate_unknown_doc_ids_skipped() -> None:
    rec = {"description": "x", "document_ids": "nonexistent"}
    mutated = annotate_with_sourced_dates(rec, _doc_dates())
    assert mutated is False
    assert rec["description"] == "x"


def test_annotate_blank_description_still_prefixes() -> None:
    rec = {"description": "", "document_ids": "111"}
    mutated = annotate_with_sourced_dates(rec, _doc_dates())
    assert mutated is True
    assert rec["description"].startswith(SOURCED_PREFIX)


def test_has_sourced_prefix() -> None:
    assert has_sourced_prefix("[sourced: 2020-01-01] hello")
    assert not has_sourced_prefix("hello")
    assert not has_sourced_prefix("")

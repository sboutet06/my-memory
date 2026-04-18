"""Pure-function tests for doc-summary composition."""
from __future__ import annotations

from extraction.retrieval_enhance import (
    _clean_content_head,
    build_doc_summary,
    transactions_extras,
)


class TestBuildDocSummary:
    def test_core_fields(self) -> None:
        out = build_doc_summary(
            metadata={
                "original_filename": "RLV_CHQ_xxx.pdf",
                "document_date": "2026-03-26",
                "document_id": "abc-123",
                "extraction_quality": "rich",
            },
            content_md="Relevé de compte cheques de mars 2026. Total debit 914,00.",
            entity_names=["Sébastien Boutet", "Mylène El Kaim"],
            structured_extras=["Category transfer_out (debit): 911.40 EUR across 14 transactions"],
        )
        assert "RLV_CHQ_xxx.pdf" in out
        assert "2026-03-26" in out
        assert "abc-123" in out
        assert "Sébastien" in out
        assert "transfer_out" in out
        # Body content intentionally excluded to avoid competing with
        # Docling content chunks.
        assert "Relevé" not in out

    def test_handles_missing_fields(self) -> None:
        out = build_doc_summary({}, "", [], None)
        assert "unknown" in out.lower()
        # Must still produce something, never crash.
        assert len(out) > 0

    def test_excludes_body_content(self) -> None:
        marker = "zzBODYzz" * 100
        out = build_doc_summary({"original_filename": "y.pdf"}, marker, [], None)
        # Summary intentionally excludes body content to avoid competing
        # with Docling content chunks in chunks_vdb top-K.
        assert "zzBODYzz" not in out

    def test_caps_entity_list(self) -> None:
        names = [f"Entity {i}" for i in range(200)]
        out = build_doc_summary(
            {"original_filename": "z.pdf"}, "", names, None,
        )
        # Not more than the cap + the "Key entities:" prefix.
        assert out.count("Entity ") <= 50


class TestTransactionsExtras:
    def test_sorts_by_total_descending(self) -> None:
        lines = transactions_extras([
            {"category": "fee", "direction": "debit", "total_amount": "2.60", "count": "1"},
            {"category": "transfer_out", "direction": "debit", "total_amount": "911.40", "count": "14"},
            {"category": "transfer_in", "direction": "credit", "total_amount": "540.00", "count": "2"},
        ])
        assert len(lines) == 3
        assert "transfer_out" in lines[0]
        assert "transfer_in" in lines[1]
        assert "fee" in lines[2]

    def test_handles_non_numeric_totals(self) -> None:
        lines = transactions_extras([
            {"category": "x", "direction": "debit", "total_amount": "not-a-number", "count": "1"},
        ])
        assert "not-a-number" in lines[0]

    def test_empty(self) -> None:
        assert transactions_extras([]) == []


class TestCleanContentHead:
    def test_drops_table_rows(self) -> None:
        content = (
            "# Header\n"
            "| a | b | c |\n"
            "|---|---|---|\n"
            "| 1 | 2 | 3 |\n"
            "Normal paragraph with real words.\n"
            "| 4 | 5 | 6 |\n"
        )
        out = _clean_content_head(content)
        assert "Normal paragraph" in out
        assert "|" not in out

    def test_drops_separator_lines(self) -> None:
        content = "---\nSome text\n===\nMore text"
        out = _clean_content_head(content)
        assert "---" not in out
        assert "Some text" in out

    def test_truncates_length(self) -> None:
        content = "\n".join([f"Paragraph number {i} with some content." for i in range(500)])
        out = _clean_content_head(content)
        assert len(out) < 3000

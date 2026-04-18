"""Diagnostics pure helpers: retention tracking on synthetic hits."""
from __future__ import annotations

from extraction.diagnostics import _expected_retention


class TestExpectedRetention:
    def test_no_expected_returns_empty(self) -> None:
        assert _expected_retention([{"document_ids": "a"}], [], {"a": "A.pdf"}) == ([], [])

    def test_seen_via_document_ids_list(self) -> None:
        hits = [{"document_ids": ["doc-1", "doc-2"]}]
        id_map = {"doc-1": "RLV_CHQ.pdf", "doc-2": "Compromis.pdf"}
        seen, missing = _expected_retention(hits, ["RLV_CHQ", "PasseportSeb"], id_map)
        assert seen == ["RLV_CHQ"]
        assert missing == ["PasseportSeb"]

    def test_seen_via_sep_joined_document_ids(self) -> None:
        hits = [{"document_ids": "doc-1<SEP>doc-2"}]
        id_map = {"doc-1": "RLV_CHQ.pdf", "doc-2": "Compromis.pdf"}
        seen, _ = _expected_retention(hits, ["Compromis"], id_map)
        assert seen == ["Compromis"]

    def test_seen_via_full_doc_id(self) -> None:
        hits = [{"full_doc_id": "doc-1"}]
        id_map = {"doc-1": "RLV_CHQ.pdf"}
        seen, missing = _expected_retention(hits, ["RLV_CHQ", "Compromis"], id_map)
        assert seen == ["RLV_CHQ"]
        assert missing == ["Compromis"]

    def test_seen_via_file_path(self) -> None:
        hits = [{"file_path": "/root/store/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee/content.md"}]
        id_map = {"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee": "X.pdf"}
        seen, _ = _expected_retention(hits, ["X"], id_map)
        assert seen == ["X"]

    def test_missing_when_no_hits(self) -> None:
        seen, missing = _expected_retention([], ["RLV_CHQ"], {})
        assert seen == []
        assert missing == ["RLV_CHQ"]

"""Router: maps a doc to its structured extractor(s)."""
from __future__ import annotations

from pathlib import Path

from packs.personal_documents.router import detect_doc_kind, extract_structured


BANK_MD_SNIPPET = """
## RELEVE DE COMPTE CHEQUES

du 26 février 2026 au 26 mars 2026

RIB : 30004 02374 00000698554 66

|   D ate | N ature des opérations | V aleur | D ébit | C rédit |
|---------|------------------------|---------|--------|---------|
|   27.02 | VIR CPTE A CPTE EMIS   | 27.02   | 100,00 |         |
"""


def _meta(filename: str) -> dict:
    return {"document_id": "d-1", "original_filename": filename}


class TestDetection:
    def test_filename_prefix_rlv(self) -> None:
        assert detect_doc_kind(_meta("RLV_CHQ_123.pdf"), "") == "bank_statement"

    def test_content_releve_de_compte(self) -> None:
        assert detect_doc_kind(_meta("other.pdf"), "RELEVE DE COMPTE CHEQUES") == "bank_statement"

    def test_unknown_kind(self) -> None:
        assert detect_doc_kind(_meta("random.pdf"), "random content") is None


class TestExtractStructured:
    def test_bank_statement_returns_transactions(self) -> None:
        meta = _meta("RLV_CHQ_123.pdf")
        meta["document_id"] = "bank-doc"
        out = extract_structured(meta, BANK_MD_SNIPPET)
        assert out is not None
        assert out["kind"] == "bank_statement"
        assert len(out["transactions"]) == 1
        tx = out["transactions"][0]
        assert tx.source_doc_id == "bank-doc"

    def test_non_matching_doc_returns_none(self) -> None:
        assert extract_structured(_meta("random.pdf"), "random") is None

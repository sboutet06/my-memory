"""Bank-statement extractor — markdown table → Transaction list."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from packs.personal_documents.extractors.bank_statement import (
    extract_transactions,
    parse_amount_fr,
    parse_day_month,
    parse_statement_period,
    parse_rib,
)


class TestParseAmountFR:
    @pytest.mark.parametrize("raw,expected", [
        ("100,00", Decimal("100.00")),
        ("1 209,10", Decimal("1209.10")),
        ("12 345,67", Decimal("12345.67")),
        (" 65,00 ", Decimal("65.00")),
    ])
    def test_parses(self, raw, expected) -> None:
        assert parse_amount_fr(raw) == expected

    def test_empty_returns_none(self) -> None:
        assert parse_amount_fr("") is None
        assert parse_amount_fr("   ") is None


class TestParseDayMonth:
    def test_within_period(self) -> None:
        period = (date(2026, 2, 26), date(2026, 3, 26))
        assert parse_day_month("27.02", period) == date(2026, 2, 27)
        assert parse_day_month(" 2.03", period) == date(2026, 3, 2)

    def test_crossing_year_boundary(self) -> None:
        period = (date(2025, 12, 20), date(2026, 1, 20))
        # 15.01 should resolve to 2026 (end-year side)
        assert parse_day_month("15.01", period) == date(2026, 1, 15)
        # 28.12 should resolve to 2025 (start-year side)
        assert parse_day_month("28.12", period) == date(2025, 12, 28)

    def test_empty_returns_none(self) -> None:
        assert parse_day_month("", (date(2026, 2, 26), date(2026, 3, 26))) is None


class TestParseStatementPeriod:
    def test_finds_french_header(self) -> None:
        text = (
            "RIB : 30004 02374 00000698554 66\n\n"
            "du 26 février 2026 au 26 mars 2026\n\n"
            "body"
        )
        assert parse_statement_period(text) == (
            date(2026, 2, 26), date(2026, 3, 26),
        )

    def test_returns_none_when_missing(self) -> None:
        assert parse_statement_period("no date here") is None


class TestParseRIB:
    def test_extracts_digits(self) -> None:
        text = "RIB : 30004 02374 00000698554 66\nIBAN: FR76..."
        assert parse_rib(text) == "30004 02374 00000698554 66"

    def test_missing(self) -> None:
        assert parse_rib("no rib") is None


class TestExtractTransactions:
    BASIC_MD = """
Some preamble

du 26 février 2026 au 26 mars 2026

RIB : 30004 02374 00000698554 66

|   D ate | N ature des opérations                                                                                                                |   V aleur | D ébit   | C rédit   |
|---------|---------------------------------------------------------------------------------------------------------------------------------------|-----------|----------|-----------|
|         | SOLDE CREDITEUR AU 26.02.2026                                                                                                         |           |          | 1 209,10  |
|   27.02 | VIR CPTE A CPTE EMIS /MOTIF VACANCES                                                                                                   |     27.02 | 100,00   |           |
|    2.03 | VIR SEPA RECU /DE MYLENE                                                                                                              |      2.03 |          | 270,00    |
|    2.03 | CARTE X1234 CARREFOUR                                                                                                                 |      2.03 | 42,50    |           |
| TOTAL DES OPERATIONS | TOTAL DES OPERATIONS | TOTAL DES OPERATIONS | 142,50 | 270,00 |
| SOLDE CREDITEUR AU 26.03.2026 | SOLDE CREDITEUR AU 26.03.2026 | SOLDE CREDITEUR AU 26.03.2026 | | 1336,60 |
"""

    def test_parses_three_transactions_skipping_balance_and_total(self) -> None:
        txs = extract_transactions(self.BASIC_MD, source_doc_id="doc-1")
        assert len(txs) == 3
        descs = [t.description for t in txs]
        assert "VIR CPTE A CPTE EMIS /MOTIF VACANCES" in descs[0]
        assert txs[0].debit == Decimal("100.00")
        assert txs[0].date == date(2026, 2, 27)
        assert txs[1].credit == Decimal("270.00")
        assert txs[1].category == "transfer_in"
        assert txs[2].category == "card_payment"

    def test_categorization_in_output(self) -> None:
        txs = extract_transactions(self.BASIC_MD, source_doc_id="doc-1")
        cats = [t.category for t in txs]
        assert cats == ["transfer_out", "transfer_in", "card_payment"]

    def test_rib_attached(self) -> None:
        txs = extract_transactions(self.BASIC_MD, source_doc_id="doc-1")
        assert all(t.account_rib == "30004 02374 00000698554 66" for t in txs)

    def test_empty_markdown(self) -> None:
        assert extract_transactions("no table here", source_doc_id="x") == []

    def test_missing_period_skips(self) -> None:
        md_no_period = self.BASIC_MD.replace("du 26 février 2026 au 26 mars 2026", "")
        # Without a period, date resolution is impossible — returns empty.
        assert extract_transactions(md_no_period, source_doc_id="x") == []

"""Transaction schema — shape, validation, category classification."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from packs.personal_documents.schemas.transaction import (
    Transaction,
    TransactionDirection,
    classify_category,
)


class TestClassify:
    @pytest.mark.parametrize("description,expected", [
        ("VIR CPTE A CPTE EMIS /MOTIF VACANCES", "transfer_out"),
        ("VIR SCT INST EMIS /MOTIF SEANCE", "transfer_out"),
        ("VIR SEPA RECU /DE EL KAIM", "transfer_in"),
        ("CARTE X1234 CARREFOUR", "card_payment"),
        ("PRLV ORANGE SA", "direct_debit"),
        ("CHEQUE N.000123", "cheque"),
        ("COMMISSIONS", "fee"),
        ("INTERETS CREDITEURS", "interest"),
        ("* FRAIS TENUE DE COMPTE", "fee"),
        ("SOLDE CREDITEUR AU 26.02.2026", "balance"),
        ("Random thing no prefix", "other"),
    ])
    def test_category_by_prefix(self, description, expected) -> None:
        assert classify_category(description) == expected


class TestTransaction:
    def _t(self, **over) -> Transaction:
        defaults = dict(
            date=date(2026, 2, 27),
            value_date=date(2026, 2, 27),
            description="VIR SCT INST EMIS",
            debit=Decimal("100.00"),
            credit=None,
            source_doc_id="abc-123",
        )
        defaults.update(over)
        return Transaction(**defaults)

    def test_minimal_debit(self) -> None:
        t = self._t()
        assert t.direction == TransactionDirection.DEBIT
        assert t.category == "transfer_out"  # auto-classified

    def test_credit_direction(self) -> None:
        t = self._t(debit=None, credit=Decimal("270.00"),
                    description="VIR SEPA RECU /DE MYLENE")
        assert t.direction == TransactionDirection.CREDIT
        assert t.category == "transfer_in"

    def test_cannot_have_both_debit_and_credit(self) -> None:
        with pytest.raises(ValidationError):
            self._t(debit=Decimal("10"), credit=Decimal("10"))

    def test_must_have_one_of_debit_or_credit(self) -> None:
        with pytest.raises(ValidationError):
            self._t(debit=None, credit=None)

    def test_negative_amount_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._t(debit=Decimal("-10"))

    def test_override_category(self) -> None:
        t = self._t(category="custom_cat")
        assert t.category == "custom_cat"

    def test_amount_property_always_positive_with_direction(self) -> None:
        debit_t = self._t(debit=Decimal("50.00"))
        credit_t = self._t(debit=None, credit=Decimal("270.00"),
                           description="VIR SEPA RECU")
        assert debit_t.amount == Decimal("50.00")
        assert credit_t.amount == Decimal("270.00")

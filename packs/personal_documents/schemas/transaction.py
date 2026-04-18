"""Bank-transaction schema — structured record for an ingested statement row."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class TransactionDirection(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


# Ordered prefix → category map. First match wins, so put the more specific
# prefixes (e.g. "VIR SCT INST" before "VIR") earlier.
_PREFIX_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("SOLDE", "balance"),
    ("VIR SEPA RECU", "transfer_in"),
    ("VIR CPTE A CPTE RECU", "transfer_in"),
    ("VIR RECU", "transfer_in"),
    ("VIR SCT INST RECU", "transfer_in"),
    ("VIR CPTE A CPTE EMIS", "transfer_out"),
    ("VIR SCT INST EMIS", "transfer_out"),
    ("VIR SEPA EMIS", "transfer_out"),
    ("VIR EMIS", "transfer_out"),
    ("VIR", "transfer_out"),   # bare VIR falls back to outgoing
    ("CARTE", "card_payment"),
    ("PRLV", "direct_debit"),
    ("CHEQUE", "cheque"),
    ("COMMISSION", "fee"),
    ("FRAIS", "fee"),
    ("AGIOS", "fee"),
    ("INTERETS", "interest"),
    ("DEPOT", "deposit"),
    ("RETRAIT", "withdrawal"),
)


def classify_category(description: str) -> str:
    """Infer a coarse category from the description prefix.

    Deterministic and language-local (French bank-statement conventions).
    Returns `other` on no match — the LLM can re-categorize post-hoc via
    corrections if needed.
    """
    normalized = description.strip().lstrip("*").strip().upper()
    for prefix, category in _PREFIX_CATEGORIES:
        if normalized.startswith(prefix):
            return category
    return "other"


class Transaction(BaseModel):
    """One row from a bank statement's transaction table."""

    date: date
    value_date: date
    description: str = Field(min_length=1)
    debit: Optional[Decimal] = None
    credit: Optional[Decimal] = None
    category: Optional[str] = None
    account_rib: Optional[str] = None
    source_doc_id: str

    @model_validator(mode="after")
    def _validate_amounts_and_fill_category(self) -> "Transaction":
        if self.debit is None and self.credit is None:
            raise ValueError("transaction must have either debit or credit")
        if self.debit is not None and self.credit is not None:
            raise ValueError("transaction cannot have both debit and credit")
        for name, value in (("debit", self.debit), ("credit", self.credit)):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative (got {value})")
        if self.category is None:
            object.__setattr__(self, "category", classify_category(self.description))
        return self

    @property
    def direction(self) -> TransactionDirection:
        return TransactionDirection.DEBIT if self.debit is not None else TransactionDirection.CREDIT

    @property
    def amount(self) -> Decimal:
        """Unsigned amount; pair with `direction` for signed views."""
        return self.debit if self.debit is not None else self.credit  # type: ignore[return-value]

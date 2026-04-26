"""Task 6.2 — bank statement pack emits FactResult alongside LightRAG nodes.

Verifies: one Fact + one Claim per transaction, Claim chain correct,
IDs deterministic, subject_id references the account entity.
"""
from __future__ import annotations

import pytest

from facts.models import FactResult
from packs.personal_documents.extractors.bank_statement import extract_transactions
from packs.personal_documents.injector import plan_transaction_facts


# Same fixture as test_bank_statement_extractor.py — 3 real transactions,
# 1 SOLDE and 1 TOTAL row skipped by the extractor.
BASIC_MD = """\

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


@pytest.fixture
def transactions():
    return extract_transactions(BASIC_MD, source_doc_id="doc-stmt-1")


@pytest.fixture
def fact_result(transactions):
    return plan_transaction_facts(transactions)


class TestPlanTransactionFacts:
    def test_returns_fact_result(self, fact_result: FactResult) -> None:
        assert isinstance(fact_result, FactResult)

    def test_one_fact_per_transaction(self, fact_result: FactResult, transactions) -> None:
        assert len(fact_result.facts) == len(transactions) == 3

    def test_one_claim_per_transaction(self, fact_result: FactResult, transactions) -> None:
        assert len(fact_result.claims) == len(transactions) == 3

    def test_claim_references_correct_fact(self, fact_result: FactResult) -> None:
        fact_ids = {f.id for f in fact_result.facts}
        for claim in fact_result.claims:
            assert claim.fact_id in fact_ids, (
                f"Claim {claim.id!r} references unknown fact {claim.fact_id!r}"
            )

    def test_facts_predicate_is_transaction(self, fact_result: FactResult) -> None:
        assert all(f.predicate == "transaction" for f in fact_result.facts)

    def test_facts_source_doc_matches(self, fact_result: FactResult) -> None:
        assert all(f.source_doc_id == "doc-stmt-1" for f in fact_result.facts)

    def test_claims_source_doc_matches(self, fact_result: FactResult) -> None:
        assert all(c.source_doc_id == "doc-stmt-1" for c in fact_result.claims)

    def test_claims_confidence_is_1(self, fact_result: FactResult) -> None:
        assert all(c.confidence == 1.0 for c in fact_result.claims)

    def test_facts_confidence_is_1(self, fact_result: FactResult) -> None:
        assert all(f.confidence == 1.0 for f in fact_result.facts)

    def test_claims_extractor_identifies_bank_statement(self, fact_result: FactResult) -> None:
        assert all("bank_statement" in c.extractor for c in fact_result.claims)

    def test_subject_id_references_account(self, fact_result: FactResult) -> None:
        assert all("account" in f.subject_id for f in fact_result.facts)

    def test_fact_ids_stable_across_calls(self, transactions) -> None:
        r1 = plan_transaction_facts(transactions)
        r2 = plan_transaction_facts(transactions)
        ids1 = {f.id for f in r1.facts}
        ids2 = {f.id for f in r2.facts}
        assert ids1 == ids2

    def test_canonical_value_deterministic(self, transactions) -> None:
        r1 = plan_transaction_facts(transactions)
        r2 = plan_transaction_facts(transactions)
        cvs1 = sorted(f.canonical_value for f in r1.facts)
        cvs2 = sorted(f.canonical_value for f in r2.facts)
        assert cvs1 == cvs2

    def test_empty_transactions_returns_empty_result(self) -> None:
        result = plan_transaction_facts([])
        assert result.facts == []
        assert result.claims == []
        assert result.is_empty()

    def test_fact_value_contains_transaction_fields(self, fact_result: FactResult) -> None:
        for fact in fact_result.facts:
            assert isinstance(fact.value, dict)
            assert "date" in fact.value
            assert "amount" in fact.value
            assert "direction" in fact.value

    def test_facts_have_valid_from_set_to_transaction_date(
        self, fact_result: FactResult, transactions,
    ) -> None:
        """Phase 8.1: transaction date populates valid_from for as_of queries."""
        for fact, txn in zip(fact_result.facts, transactions):
            assert fact.valid_from == txn.date

    def test_facts_valid_to_unset_for_transactions(
        self, fact_result: FactResult,
    ) -> None:
        """Transactions are point-in-time events — valid_to stays None."""
        for fact in fact_result.facts:
            assert fact.valid_to is None

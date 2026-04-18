"""Graph injection: structured records → KG nodes + edges."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from packs.personal_documents.injector import plan_transaction_nodes
from packs.personal_documents.schemas.transaction import Transaction


def _tx(debit=None, credit=None, description="VIR X", rib="30004 02374 1"):
    return Transaction(
        date=date(2026, 2, 27), value_date=date(2026, 2, 27),
        description=description, debit=debit, credit=credit,
        account_rib=rib, source_doc_id="doc-1",
    )


class TestPlanTransactionNodes:
    def test_single_transaction_produces_node_and_two_edges(self) -> None:
        t = _tx(debit=Decimal("100.00"))
        nodes, edges = plan_transaction_nodes([t])
        tx_nodes = [n for n in nodes if n["entity_type"] == "transaction"]
        assert len(tx_nodes) == 1
        n = tx_nodes[0]
        assert n["entity_type"] == "transaction"
        # Human-readable node name carries retrieval-friendly tokens
        assert "100.00" in n["name"]
        assert "debit" in n["name"]
        assert "2026-02-27" in n["name"]
        assert n["attrs"]["amount"] == "100.00"
        assert n["attrs"]["direction"] == "debit"
        assert n["attrs"]["category"] == "transfer_out"

        # tx → account, tx → document, tx → summary, summary → document
        edge_targets = {(e["src"], e["tgt"]) for e in edges}
        assert any("30004" in tgt for _, tgt in edge_targets)
        assert any("/store/doc-1/" in tgt for _, tgt in edge_targets)
        assert any("Expense summary" in tgt for _, tgt in edge_targets)
        summary_nodes = [n for n in nodes if n["entity_type"] == "transaction_category"]
        assert len(summary_nodes) == 1
        assert summary_nodes[0]["attrs"]["total_amount"] == "100.00"

    def test_deduplicates_same_transaction(self) -> None:
        t = _tx(debit=Decimal("100.00"))
        nodes, _ = plan_transaction_nodes([t, t])
        tx_nodes = [n for n in nodes if n["entity_type"] == "transaction"]
        assert len(tx_nodes) == 1

    def test_distinct_transactions_distinct_nodes(self) -> None:
        t1 = _tx(debit=Decimal("100.00"), description="VIR A")
        t2 = _tx(debit=Decimal("200.00"), description="VIR B")
        nodes, _ = plan_transaction_nodes([t1, t2])
        tx_nodes = [n for n in nodes if n["entity_type"] == "transaction"]
        assert len(tx_nodes) == 2

    def test_account_node_emitted_once_per_rib(self) -> None:
        t1 = _tx(debit=Decimal("10.00"), rib="30004 02374 1")
        t2 = _tx(credit=Decimal("20.00"), description="VIR SEPA RECU",
                 rib="30004 02374 1")
        nodes, edges = plan_transaction_nodes([t1, t2])
        account_nodes = [n for n in nodes if n["entity_type"] == "account"]
        assert len(account_nodes) == 1
        assert account_nodes[0]["name"].startswith("account:")

    def test_no_rib_uses_anonymous_account(self) -> None:
        t = Transaction(
            date=date(2026, 2, 27), value_date=date(2026, 2, 27),
            description="CARTE X", debit=Decimal("5.00"),
            source_doc_id="doc-x",
        )
        nodes, edges = plan_transaction_nodes([t])
        # Must still emit SOMETHING linking the transaction
        assert any(n["entity_type"] == "transaction" for n in nodes)

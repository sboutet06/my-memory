"""Task 6.3 — Pack.inject_facts hook and facts/orchestrator.py.

Covers: stub pack without hook → empty FactResult; personal_documents
pack with bank_statement result → populated FactResult; orchestrator
aggregates across packs; duplicate IDs swallowed (idempotent re-run).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from facts.models import FactResult
from facts.orchestrator import run_inject_facts
from facts.store import FactStore
from packs.registry import PackRegistry


# ------------------------------------------------- minimal stub pack -----

class _StubPackNoHook:
    """Pack without inject_facts — orchestrator must skip it silently."""
    name = "stub_no_hook"
    version = "0.0.1"

    def matches(self, metadata: dict, content_md: str) -> bool:
        return False


_STUB_NO_HOOK = _StubPackNoHook()


# ------------------------------------------------- real pack fixture -----

@pytest.fixture
def registry_no_hook() -> PackRegistry:
    reg = PackRegistry()
    reg.register(_STUB_NO_HOOK)
    return reg


@pytest.fixture
def registry_with_personal_docs() -> PackRegistry:
    from packs.personal_documents import PACK
    reg = PackRegistry()
    reg.register(PACK)
    return reg


@pytest.fixture
def store(tmp_path: Path) -> FactStore:
    return FactStore(tmp_path / "facts")


@pytest.fixture
def bank_statement_result() -> dict:
    from packs.personal_documents.extractors.bank_statement import extract_transactions
    BASIC_MD = """\

du 26 février 2026 au 26 mars 2026

RIB : 30004 02374 00000698554 66

|   D ate | N ature des opérations                                                                                                                |   V aleur | D ébit   | C rédit   |
|---------|---------------------------------------------------------------------------------------------------------------------------------------|-----------|----------|-----------|
|   27.02 | VIR CPTE A CPTE EMIS /MOTIF VACANCES                                                                                                   |     27.02 | 100,00   |           |
|    2.03 | VIR SEPA RECU /DE MYLENE                                                                                                              |      2.03 |          | 270,00    |
|    2.03 | CARTE X1234 CARREFOUR                                                                                                                 |      2.03 | 42,50    |           |
| TOTAL DES OPERATIONS | TOTAL DES OPERATIONS | TOTAL DES OPERATIONS | 142,50 | 270,00 |
"""
    txs = extract_transactions(BASIC_MD, source_doc_id="doc-bs-001")
    return {"kind": "bank_statement", "transactions": txs}


# ------------------------------------------------- orchestrator tests -----

class TestRunInjectFacts:
    def test_stub_pack_without_hook_returns_empty(
        self, registry_no_hook: PackRegistry, store: FactStore,
    ) -> None:
        result = run_inject_facts(registry_no_hook, {"kind": "bank_statement"}, store)
        assert isinstance(result, FactResult)
        assert result.is_empty()

    def test_stub_pack_without_hook_does_not_raise(
        self, registry_no_hook: PackRegistry, store: FactStore,
    ) -> None:
        # Must not raise even if the result dict is empty
        run_inject_facts(registry_no_hook, {}, store)

    def test_personal_docs_pack_populates_fact_result(
        self,
        registry_with_personal_docs: PackRegistry,
        store: FactStore,
        bank_statement_result: dict,
    ) -> None:
        fr = run_inject_facts(registry_with_personal_docs, bank_statement_result, store)
        assert len(fr.facts) == 3
        assert len(fr.claims) == 3

    def test_facts_written_to_store(
        self,
        registry_with_personal_docs: PackRegistry,
        store: FactStore,
        bank_statement_result: dict,
    ) -> None:
        run_inject_facts(registry_with_personal_docs, bank_statement_result, store)
        assert store.fact_count == 3
        assert store.claim_count == 3

    def test_idempotent_rerun_does_not_raise(
        self,
        registry_with_personal_docs: PackRegistry,
        store: FactStore,
        bank_statement_result: dict,
    ) -> None:
        run_inject_facts(registry_with_personal_docs, bank_statement_result, store)
        run_inject_facts(registry_with_personal_docs, bank_statement_result, store)
        # Store count unchanged — duplicates silently skipped
        assert store.fact_count == 3
        assert store.claim_count == 3

    def test_non_matching_result_kind_returns_empty(
        self,
        registry_with_personal_docs: PackRegistry,
        store: FactStore,
    ) -> None:
        fr = run_inject_facts(registry_with_personal_docs, {"kind": "unknown_kind"}, store)
        assert fr.is_empty()


# ------------------------------------------------- pack hook unit tests --

class TestPackInjectFactsHook:
    def test_personal_docs_has_inject_facts(self) -> None:
        from packs.personal_documents import PACK
        assert callable(getattr(PACK, "inject_facts", None))

    def test_inject_facts_returns_fact_result(
        self, store: FactStore, bank_statement_result: dict,
    ) -> None:
        from packs.personal_documents import PACK
        fr = PACK.inject_facts(None, store, bank_statement_result)
        assert isinstance(fr, FactResult)

    def test_inject_facts_non_bank_statement_returns_empty(self, store: FactStore) -> None:
        from packs.personal_documents import PACK
        fr = PACK.inject_facts(None, store, {"kind": "payslip"})
        assert fr.is_empty()

    def test_inject_facts_missing_kind_returns_empty(self, store: FactStore) -> None:
        from packs.personal_documents import PACK
        fr = PACK.inject_facts(None, store, {})
        assert fr.is_empty()

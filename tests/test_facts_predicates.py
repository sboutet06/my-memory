"""Tests for facts.predicates — PredicateRegistry.

TDD: these fail until facts/predicates.py is implemented.
"""
from __future__ import annotations

import pytest

from facts.models import Predicate


class TestPredicateRegistryDefaults:
    def test_import(self) -> None:
        from facts.predicates import PredicateRegistry  # noqa: F401

    def test_empty_registry_returns_default_for_unknown(self) -> None:
        from facts.predicates import PredicateRegistry

        registry = PredicateRegistry()
        p = registry.get("completely_unknown_predicate")
        assert p.name == "completely_unknown_predicate"
        assert p.time_varying is False
        assert p.allow_multi is False

    def test_default_predicate_description_empty(self) -> None:
        from facts.predicates import PredicateRegistry

        p = PredicateRegistry().get("x")
        assert p.description == ""


class TestPredicateRegistryRegister:
    def test_register_and_retrieve(self) -> None:
        from facts.predicates import PredicateRegistry

        registry = PredicateRegistry()
        pred = Predicate(name="address", time_varying=True, allow_multi=False, description="home/work address")
        registry.register(pred)
        retrieved = registry.get("address")
        assert retrieved.time_varying is True
        assert retrieved.description == "home/work address"

    def test_register_overwrites_duplicate(self) -> None:
        from facts.predicates import PredicateRegistry

        registry = PredicateRegistry()
        registry.register(Predicate(name="address", time_varying=False))
        registry.register(Predicate(name="address", time_varying=True))
        assert registry.get("address").time_varying is True

    def test_register_multiple_predicates(self) -> None:
        from facts.predicates import PredicateRegistry

        registry = PredicateRegistry()
        registry.register(Predicate(name="birthdate", time_varying=False))
        registry.register(Predicate(name="address", time_varying=True))
        registry.register(Predicate(name="transaction", allow_multi=True))
        assert registry.get("birthdate").time_varying is False
        assert registry.get("address").time_varying is True
        assert registry.get("transaction").allow_multi is True

    def test_all_returns_registered_predicates(self) -> None:
        from facts.predicates import PredicateRegistry

        registry = PredicateRegistry()
        registry.register(Predicate(name="a"))
        registry.register(Predicate(name="b"))
        names = {p.name for p in registry.all()}
        assert names == {"a", "b"}

    def test_all_empty_registry(self) -> None:
        from facts.predicates import PredicateRegistry

        assert list(PredicateRegistry().all()) == []


class TestPredicateRegistryFromPacks:
    def test_from_packs_with_predicates_attribute(self) -> None:
        from facts.predicates import PredicateRegistry

        class FakePack:
            predicates = (
                Predicate(name="address", time_varying=True),
                Predicate(name="birthdate", time_varying=False),
            )

        registry = PredicateRegistry.from_packs([FakePack()])
        assert registry.get("address").time_varying is True
        assert registry.get("birthdate").time_varying is False

    def test_from_packs_without_predicates_attribute(self) -> None:
        from facts.predicates import PredicateRegistry

        class FakePack:
            pass

        registry = PredicateRegistry.from_packs([FakePack()])
        # No error, empty registry, defaults kick in
        p = registry.get("anything")
        assert p.time_varying is False

    def test_from_packs_multiple_packs_merged(self) -> None:
        from facts.predicates import PredicateRegistry

        class PackA:
            predicates = (Predicate(name="address", time_varying=True),)

        class PackB:
            predicates = (Predicate(name="birthdate", time_varying=False),)

        registry = PredicateRegistry.from_packs([PackA(), PackB()])
        assert registry.get("address").time_varying is True
        assert registry.get("birthdate").time_varying is False

    def test_from_packs_empty_list(self) -> None:
        from facts.predicates import PredicateRegistry

        registry = PredicateRegistry.from_packs([])
        assert list(registry.all()) == []

    def test_from_packs_later_pack_overwrites_earlier(self) -> None:
        from facts.predicates import PredicateRegistry

        class PackA:
            predicates = (Predicate(name="address", time_varying=False),)

        class PackB:
            predicates = (Predicate(name="address", time_varying=True),)

        registry = PredicateRegistry.from_packs([PackA(), PackB()])
        assert registry.get("address").time_varying is True


class TestPersonalDocumentsPackPredicates:
    """personal_documents pack must declare its predicates tuple."""

    def test_pack_has_predicates_attribute(self) -> None:
        from packs.personal_documents import PACK

        assert hasattr(PACK, "predicates"), "personal_documents pack must expose `predicates`"

    def test_predicates_is_tuple_of_predicate(self) -> None:
        from packs.personal_documents import PACK

        assert isinstance(PACK.predicates, tuple)
        for p in PACK.predicates:
            assert isinstance(p, Predicate)

    def test_transaction_predicate_allow_multi(self) -> None:
        from packs.personal_documents import PACK

        txn = next((p for p in PACK.predicates if p.name == "transaction"), None)
        assert txn is not None, "personal_documents must declare a 'transaction' predicate"
        assert txn.allow_multi is True

    def test_address_predicate_time_varying(self) -> None:
        from packs.personal_documents import PACK

        addr = next((p for p in PACK.predicates if p.name == "address"), None)
        assert addr is not None, "personal_documents must declare an 'address' predicate"
        assert addr.time_varying is True

    def test_birthdate_predicate_invariant(self) -> None:
        from packs.personal_documents import PACK

        bd = next((p for p in PACK.predicates if p.name == "birthdate"), None)
        assert bd is not None, "personal_documents must declare a 'birthdate' predicate"
        assert bd.time_varying is False
        assert bd.allow_multi is False

"""Tests for GET /entities/{entity_id}?as_of=YYYY-MM-DD — Phase 8.5.

Returns facts about an entity, optionally filtered by as_of date.
A fact is in scope at as_of D iff:
  (valid_from is None OR valid_from <= D)
  AND (valid_to is None OR valid_to >= D)
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_store
from facts.models import Fact
from facts.store import FactStore


def _make_fact(
    subject_id: str,
    predicate: str,
    value: str,
    source_doc_id: str,
    valid_from: date | None = None,
    valid_to: date | None = None,
) -> Fact:
    return Fact(
        subject_id=subject_id,
        predicate=predicate,
        canonical_value=value,
        value=value,
        source_doc_id=source_doc_id,
        valid_from=valid_from,
        valid_to=valid_to,
    )


@pytest.fixture
def store(tmp_path: Path) -> FactStore:
    return FactStore(tmp_path / "api_temporal")


@pytest.fixture
def client(store: FactStore):
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def populated_store(store: FactStore) -> FactStore:
    """Three addresses for 'p1' across time + an unrelated entity."""
    store.append_fact(_make_fact(
        "p1", "address", "10 rue A", "doc-1",
        valid_from=date(2010, 1, 1), valid_to=date(2014, 12, 31),
    ))
    store.append_fact(_make_fact(
        "p1", "address", "20 rue B", "doc-2",
        valid_from=date(2015, 1, 1), valid_to=date(2019, 12, 31),
    ))
    store.append_fact(_make_fact(
        "p1", "address", "30 rue C", "doc-3",
        valid_from=date(2020, 1, 1),
    ))  # still valid
    store.append_fact(_make_fact(
        "p1", "birthdate", "1985-04-12", "doc-4",
        valid_from=date(1985, 4, 12),
    ))
    store.append_fact(_make_fact(
        "p2", "address", "999 rue X", "doc-99",
        valid_from=date(2010, 1, 1),
    ))
    return store


class TestEntityEndpoint:
    def test_unknown_entity_returns_empty_facts(self, client) -> None:
        response = client.get("/entities/nonexistent")
        assert response.status_code == 200
        assert response.json() == {"entity_id": "nonexistent", "facts": []}

    def test_returns_all_facts_without_as_of(
        self, client, populated_store: FactStore,
    ) -> None:
        data = client.get("/entities/p1").json()
        # 4 facts about p1 (3 addresses + 1 birthdate)
        assert len(data["facts"]) == 4

    def test_other_entities_excluded(
        self, client, populated_store: FactStore,
    ) -> None:
        data = client.get("/entities/p1").json()
        for f in data["facts"]:
            assert f["subject_id"] == "p1"

    def test_as_of_filter_2012_returns_first_address(
        self, client, populated_store: FactStore,
    ) -> None:
        data = client.get("/entities/p1?as_of=2012-06-01").json()
        addr_facts = [f for f in data["facts"] if f["predicate"] == "address"]
        assert len(addr_facts) == 1
        assert "10 rue A" in addr_facts[0]["canonical_value"]

    def test_as_of_filter_2017_returns_second_address(
        self, client, populated_store: FactStore,
    ) -> None:
        data = client.get("/entities/p1?as_of=2017-03-15").json()
        addr_facts = [f for f in data["facts"] if f["predicate"] == "address"]
        assert len(addr_facts) == 1
        assert "20 rue B" in addr_facts[0]["canonical_value"]

    def test_as_of_filter_2024_returns_open_ended_address(
        self, client, populated_store: FactStore,
    ) -> None:
        data = client.get("/entities/p1?as_of=2024-12-31").json()
        addr_facts = [f for f in data["facts"] if f["predicate"] == "address"]
        assert len(addr_facts) == 1
        assert "30 rue C" in addr_facts[0]["canonical_value"]

    def test_as_of_filter_excludes_facts_not_yet_valid(
        self, client, populated_store: FactStore,
    ) -> None:
        # 2008 — before any address valid_from
        data = client.get("/entities/p1?as_of=2008-01-01").json()
        addr_facts = [f for f in data["facts"] if f["predicate"] == "address"]
        assert len(addr_facts) == 0

    def test_as_of_filter_includes_birthdate_invariant(
        self, client, populated_store: FactStore,
    ) -> None:
        # birthdate is invariant — present at any as_of >= 1985-04-12
        data = client.get("/entities/p1?as_of=2017-03-15").json()
        bd_facts = [f for f in data["facts"] if f["predicate"] == "birthdate"]
        assert len(bd_facts) == 1

    def test_response_contains_entity_id(
        self, client, populated_store: FactStore,
    ) -> None:
        data = client.get("/entities/p1?as_of=2017-03-15").json()
        assert data["entity_id"] == "p1"

    def test_response_contains_as_of_when_set(
        self, client, populated_store: FactStore,
    ) -> None:
        data = client.get("/entities/p1?as_of=2017-03-15").json()
        assert data["as_of"] == "2017-03-15"

    def test_response_omits_as_of_when_not_set(
        self, client, populated_store: FactStore,
    ) -> None:
        data = client.get("/entities/p1").json()
        assert "as_of" not in data or data.get("as_of") is None

    def test_malformed_as_of_returns_422(
        self, client, populated_store: FactStore,
    ) -> None:
        response = client.get("/entities/p1?as_of=not-a-date")
        assert response.status_code == 422

    def test_facts_for_entity_with_unset_valid_from_always_visible(
        self, client, store: FactStore,
    ) -> None:
        store.append_fact(_make_fact("p_x", "note", "always there", "doc-1"))
        data = client.get("/entities/p_x?as_of=1900-01-01").json()
        assert len(data["facts"]) == 1

    def test_other_entity_isolated(
        self, client, populated_store: FactStore,
    ) -> None:
        data = client.get("/entities/p2").json()
        assert len(data["facts"]) == 1
        assert data["facts"][0]["canonical_value"] == "999 rue X"

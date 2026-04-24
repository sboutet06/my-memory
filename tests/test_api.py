"""Tests for GET /health and GET /facts/{fact_id}.

Uses starlette.testclient.TestClient (httpx under the hood, no real
uvicorn started) with dependency_overrides for the FactStore.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_store
from facts.models import Claim, Fact
from facts.store import FactStore


@pytest.fixture
def store(tmp_path: Path) -> FactStore:
    return FactStore(tmp_path / "api_facts")


@pytest.fixture
def client(store: FactStore):
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestHealth:
    def test_returns_200(self, client) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_returns_ok_payload(self, client) -> None:
        assert client.get("/health").json() == {"status": "ok"}


class TestGetFact:
    def _valid_sha256(self) -> str:
        return "a" * 64

    def test_missing_fact_returns_404(self, client) -> None:
        response = client.get(f"/facts/{self._valid_sha256()}")
        assert response.status_code == 404

    def test_malformed_fact_id_too_short_returns_422(self, client) -> None:
        response = client.get("/facts/abc123")
        assert response.status_code == 422

    def test_malformed_fact_id_non_hex_returns_422(self, client) -> None:
        response = client.get(f"/facts/{'z' * 64}")
        assert response.status_code == 422

    def test_found_fact_returns_200(self, client, store: FactStore) -> None:
        fact = Fact(
            subject_id="e1",
            predicate="address",
            canonical_value="Paris",
            source_doc_id="doc-1",
        )
        store.append_fact(fact)
        response = client.get(f"/facts/{fact.id}")
        assert response.status_code == 200

    def test_response_contains_fact_payload(self, client, store: FactStore) -> None:
        fact = Fact(
            subject_id="e1",
            predicate="address",
            canonical_value="Paris",
            source_doc_id="doc-1",
        )
        store.append_fact(fact)
        data = client.get(f"/facts/{fact.id}").json()
        assert data["fact"]["id"] == fact.id
        assert data["fact"]["predicate"] == "address"
        assert data["fact"]["subject_id"] == "e1"

    def test_response_contains_claims_list(self, client, store: FactStore) -> None:
        fact = Fact(
            subject_id="e1",
            predicate="address",
            canonical_value="Paris",
            source_doc_id="doc-1",
        )
        claim = Claim(
            fact_id=fact.id,
            source_doc_id="doc-1",
            extractor="pack:test@1.0",
        )
        store.append_fact(fact)
        store.append_claim(claim)
        data = client.get(f"/facts/{fact.id}").json()
        assert len(data["claims"]) == 1
        assert data["claims"][0]["fact_id"] == fact.id

    def test_response_conflicts_empty_until_phase7(self, client, store: FactStore) -> None:
        fact = Fact(
            subject_id="e1",
            predicate="address",
            canonical_value="Paris",
            source_doc_id="doc-1",
        )
        store.append_fact(fact)
        data = client.get(f"/facts/{fact.id}").json()
        assert data["conflicts"] == []

    def test_fact_id_correct_length_but_uppercase_returns_422(self, client) -> None:
        response = client.get(f"/facts/{'A' * 64}")
        assert response.status_code == 422

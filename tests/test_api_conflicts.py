"""Tests for GET /conflicts, GET /conflicts/{id}, POST /conflicts/{id}/resolve.

Phase 7 — conflict endpoints. Uses TestClient with dependency_overrides.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_store
from facts.models import Conflict, Fact
from facts.store import FactStore


def _make_fact(subject_id: str, predicate: str, value: str, doc_id: str) -> Fact:
    return Fact(
        subject_id=subject_id,
        predicate=predicate,
        canonical_value=value,
        value=value,
        source_doc_id=doc_id,
    )


def _make_conflict(subject_id: str, predicate: str, fact_ids: list[str]) -> Conflict:
    return Conflict(
        subject_id=subject_id,
        predicate=predicate,
        competing_fact_ids=fact_ids,
        status="open",
    )


@pytest.fixture
def store(tmp_path: Path) -> FactStore:
    return FactStore(tmp_path / "api_conflicts")


@pytest.fixture
def client(store: FactStore):
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestListConflicts:
    def test_empty_store_returns_empty_list(self, client, store: FactStore) -> None:
        response = client.get("/conflicts")
        assert response.status_code == 200
        assert response.json() == {"conflicts": [], "total": 0}

    def test_returns_open_conflicts(self, client, store: FactStore) -> None:
        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        store.append_fact(f1)
        store.append_fact(f2)
        c = _make_conflict("e1", "birthdate", [f1.id, f2.id])
        store.append_conflict(c)
        data = client.get("/conflicts").json()
        assert data["total"] == 1
        assert len(data["conflicts"]) == 1

    def test_status_filter_open(self, client, store: FactStore) -> None:
        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        store.append_fact(f1)
        store.append_fact(f2)
        c = _make_conflict("e1", "birthdate", [f1.id, f2.id])
        store.append_conflict(c)
        data = client.get("/conflicts?status=open").json()
        assert data["total"] == 1

    def test_status_filter_resolved_returns_empty(self, client, store: FactStore) -> None:
        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        store.append_fact(f1)
        store.append_fact(f2)
        c = _make_conflict("e1", "birthdate", [f1.id, f2.id])
        store.append_conflict(c)
        data = client.get("/conflicts?status=resolved_manually").json()
        assert data["total"] == 0

    def test_limit_parameter(self, client, store: FactStore) -> None:
        for i in range(3):
            fa = _make_fact(f"e{i}", "birthdate", f"198{i}-01-01", f"doc-{i}a")
            fb = _make_fact(f"e{i}", "birthdate", f"199{i}-06-06", f"doc-{i}b")
            store.append_fact(fa)
            store.append_fact(fb)
            store.append_conflict(_make_conflict(f"e{i}", "birthdate", [fa.id, fb.id]))
        data = client.get("/conflicts?limit=2").json()
        assert len(data["conflicts"]) == 2

    def test_conflict_payload_has_required_fields(self, client, store: FactStore) -> None:
        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        store.append_fact(f1)
        store.append_fact(f2)
        c = _make_conflict("e1", "birthdate", [f1.id, f2.id])
        store.append_conflict(c)
        item = client.get("/conflicts").json()["conflicts"][0]
        assert "id" in item
        assert item["subject_id"] == "e1"
        assert item["predicate"] == "birthdate"
        assert item["status"] == "open"
        assert "competing_fact_ids" in item


class TestGetConflict:
    def test_missing_conflict_returns_404(self, client) -> None:
        response = client.get(f"/conflicts/{'a' * 64}")
        assert response.status_code == 404

    def test_malformed_id_returns_422(self, client) -> None:
        response = client.get("/conflicts/not-a-hash")
        assert response.status_code == 422

    def test_found_conflict_returns_200(self, client, store: FactStore) -> None:
        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        store.append_fact(f1)
        store.append_fact(f2)
        c = _make_conflict("e1", "birthdate", [f1.id, f2.id])
        store.append_conflict(c)
        response = client.get(f"/conflicts/{c.id}")
        assert response.status_code == 200

    def test_detail_includes_competing_facts_and_claims(
        self, client, store: FactStore
    ) -> None:
        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        store.append_fact(f1)
        store.append_fact(f2)
        c = _make_conflict("e1", "birthdate", [f1.id, f2.id])
        store.append_conflict(c)
        data = client.get(f"/conflicts/{c.id}").json()
        assert data["conflict"]["id"] == c.id
        assert len(data["competing_facts"]) == 2
        assert "claims" in data

    def test_detail_competing_facts_have_values(
        self, client, store: FactStore
    ) -> None:
        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        store.append_fact(f1)
        store.append_fact(f2)
        c = _make_conflict("e1", "birthdate", [f1.id, f2.id])
        store.append_conflict(c)
        data = client.get(f"/conflicts/{c.id}").json()
        values = {f["canonical_value"] for f in data["competing_facts"]}
        assert "1985-01-01" in values
        assert "1986-02-02" in values


class TestResolveConflict:
    def test_resolve_stub_returns_501(self, client, store: FactStore) -> None:
        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        store.append_fact(f1)
        store.append_fact(f2)
        c = _make_conflict("e1", "birthdate", [f1.id, f2.id])
        store.append_conflict(c)
        response = client.post(f"/conflicts/{c.id}/resolve", json={"winner": f1.id})
        assert response.status_code == 501

    def test_resolve_missing_conflict_returns_404(self, client) -> None:
        response = client.post(f"/conflicts/{'a' * 64}/resolve", json={})
        assert response.status_code == 404


class TestGetFactConflicts:
    """GET /facts/{id} now returns real conflicts list (Phase 7)."""

    def test_fact_with_conflict_returns_conflict_list(
        self, client, store: FactStore
    ) -> None:
        f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
        f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
        store.append_fact(f1)
        store.append_fact(f2)
        c = _make_conflict("e1", "birthdate", [f1.id, f2.id])
        store.append_conflict(c)
        data = client.get(f"/facts/{f1.id}").json()
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["id"] == c.id

    def test_fact_without_conflict_returns_empty_list(
        self, client, store: FactStore
    ) -> None:
        f = _make_fact("e1", "address", "Paris", "doc-1")
        store.append_fact(f)
        data = client.get(f"/facts/{f.id}").json()
        assert data["conflicts"] == []

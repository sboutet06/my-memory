"""Index-node planner — pure functions, no LightRAG dependency."""
from __future__ import annotations

from extraction.index_nodes import (
    CATALOG_PREFIX,
    ENTITY_PROFILE_PREFIX,
    plan_index_nodes,
)

# Canonical store metadata shape: {doc_id: {document_id, original_filename, ...}}


def _meta(*doc_ids: str) -> dict:
    return {d: {"document_id": d, "original_filename": f"{d}.pdf"} for d in doc_ids}


def _node(name: str, entity_type: str, doc_ids: str) -> tuple[str, dict]:
    return name, {
        "entity_type": entity_type,
        "document_ids": doc_ids,
        "description": f"[sourced: 2020-01-01] {name}",
    }


class TestEntityProfile:
    def test_entity_with_one_doc_has_no_profile(self) -> None:
        graph = dict([
            _node("Alice", "person", "doc-1"),
        ])
        meta = _meta("doc-1")
        plan = plan_index_nodes(graph, meta, min_docs_for_profile=2)
        assert all(not n["name"].startswith(ENTITY_PROFILE_PREFIX) for n in plan)

    def test_entity_with_many_docs_gets_profile(self) -> None:
        graph = dict([
            _node("Alice", "person", "doc-1<SEP>doc-2<SEP>doc-3"),
        ])
        meta = _meta("doc-1", "doc-2", "doc-3")
        plan = plan_index_nodes(graph, meta)
        profiles = [n for n in plan if n["name"].startswith(ENTITY_PROFILE_PREFIX)]
        assert len(profiles) == 1
        p = profiles[0]
        assert p["name"] == f"{ENTITY_PROFILE_PREFIX}Alice"
        assert p["entity_type"] == "entity_profile"
        assert "doc-1" in p["description"]
        assert "doc-2" in p["description"]
        assert "/store/doc-1/" in p["description"]
        assert "Alice" in p["description"]

    def test_skip_low_signal_entity_types(self) -> None:
        # Numeric-type entities shouldn't generate profiles even with many docs.
        graph = dict([
            _node("100,00", "amount", "doc-1<SEP>doc-2<SEP>doc-3"),
            _node("Alice", "person", "doc-1<SEP>doc-2"),
        ])
        meta = _meta("doc-1", "doc-2", "doc-3")
        plan = plan_index_nodes(graph, meta)
        names = [n["name"] for n in plan if n["name"].startswith(ENTITY_PROFILE_PREFIX)]
        assert names == [f"{ENTITY_PROFILE_PREFIX}Alice"]

    def test_profile_for_organization(self) -> None:
        graph = dict([
            _node("Intel Corp", "organization", "doc-1<SEP>doc-2"),
        ])
        meta = _meta("doc-1", "doc-2")
        plan = plan_index_nodes(graph, meta)
        assert any(n["name"] == f"{ENTITY_PROFILE_PREFIX}Intel Corp" for n in plan)


class TestCatalog:
    def test_type_with_few_entities_no_catalog(self) -> None:
        graph = dict([
            _node("Only vehicle", "vehicle", "doc-1"),
        ])
        meta = _meta("doc-1")
        plan = plan_index_nodes(graph, meta, min_entities_for_catalog=2)
        assert all(not n["name"].startswith(CATALOG_PREFIX) for n in plan)

    def test_type_with_multiple_entities_across_docs_gets_catalog(self) -> None:
        graph = dict([
            _node("Zoe", "vehicle", "doc-1"),
            _node("Renault", "vehicle", "doc-2"),
            _node("Alice", "person", "doc-1"),
        ])
        meta = _meta("doc-1", "doc-2")
        plan = plan_index_nodes(graph, meta)
        cats = [n for n in plan if n["name"].startswith(CATALOG_PREFIX)]
        assert any(c["name"] == f"{CATALOG_PREFIX}vehicle" for c in cats)

    def test_catalog_lists_members_and_docs(self) -> None:
        graph = dict([
            _node("Zoe", "vehicle", "doc-1"),
            _node("Renault", "vehicle", "doc-2"),
        ])
        meta = _meta("doc-1", "doc-2")
        plan = plan_index_nodes(graph, meta)
        cat = next(n for n in plan if n["name"].startswith(CATALOG_PREFIX))
        assert "Zoe" in cat["description"]
        assert "Renault" in cat["description"]
        assert "/store/doc-1/" in cat["description"]
        assert "/store/doc-2/" in cat["description"]

    def test_catalog_skips_low_signal_types(self) -> None:
        graph = dict([
            _node("100,00", "amount", "doc-1"),
            _node("200,00", "amount", "doc-2"),
        ])
        meta = _meta("doc-1", "doc-2")
        plan = plan_index_nodes(graph, meta)
        assert not any(n["name"] == f"{CATALOG_PREFIX}amount" for n in plan)


class TestExtraLowSignalTypes:
    def test_without_extras_pack_types_surface(self) -> None:
        # With no packs, `transaction` entities ARE profileable — core
        # only hides its own always-noisy types (amount/date/identifier).
        graph = dict([
            _node("tx-abc", "transaction", "doc-1<SEP>doc-2"),
        ])
        meta = _meta("doc-1", "doc-2")
        plan = plan_index_nodes(graph, meta)
        names = [n["name"] for n in plan if n["name"].startswith(ENTITY_PROFILE_PREFIX)]
        assert names == [f"{ENTITY_PROFILE_PREFIX}tx-abc"]

    def test_with_pack_low_signal_hides_pack_types(self) -> None:
        graph = dict([
            _node("tx-abc", "transaction", "doc-1<SEP>doc-2"),
            _node("Alice", "person", "doc-1<SEP>doc-2"),
        ])
        meta = _meta("doc-1", "doc-2")
        plan = plan_index_nodes(
            graph, meta,
            extra_low_signal_types=("transaction", "account"),
        )
        names = [n["name"] for n in plan if n["name"].startswith(ENTITY_PROFILE_PREFIX)]
        assert names == [f"{ENTITY_PROFILE_PREFIX}Alice"]


class TestIdempotency:
    def test_planner_is_pure(self) -> None:
        graph = dict([
            _node("Alice", "person", "doc-1<SEP>doc-2"),
            _node("Zoe", "vehicle", "doc-1"),
            _node("Bob", "person", "doc-3"),
        ])
        meta = _meta("doc-1", "doc-2", "doc-3")
        a = plan_index_nodes(graph, meta)
        b = plan_index_nodes(graph, meta)
        assert a == b

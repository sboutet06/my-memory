"""Tests for conflict correction YAML: emit, load, and apply.

TDD: these fail until corrections/conflict_io.py is implemented.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from facts.models import Conflict, Fact
from facts.store import FactStore


def _make_conflict(subject_id: str, predicate: str, fact_ids: list[str]) -> Conflict:
    return Conflict(
        subject_id=subject_id,
        predicate=predicate,
        competing_fact_ids=fact_ids,
        status="open",
    )


def _make_fact(subject_id: str, predicate: str, value: str, source_doc_id: str) -> Fact:
    return Fact(
        subject_id=subject_id,
        predicate=predicate,
        canonical_value=value,
        value=value,
        source_doc_id=source_doc_id,
    )


@pytest.fixture
def tmp_store(tmp_path: Path) -> FactStore:
    f1 = _make_fact("e1", "birthdate", "1985-01-01", "doc-1")
    f2 = _make_fact("e1", "birthdate", "1986-02-02", "doc-2")
    store = FactStore(tmp_path / "facts")
    store.append_fact(f1)
    store.append_fact(f2)
    conflict = _make_conflict("e1", "birthdate", [f1.id, f2.id])
    store.append_conflict(conflict)
    return store


@pytest.fixture
def tmp_corrections_root(tmp_path: Path) -> Path:
    root = tmp_path / "corrections"
    root.mkdir()
    return root


class TestConflictSchemas:
    def test_import(self) -> None:
        from corrections.derivation_schemas import ConflictCorrection  # noqa: F401

    def test_conflict_correction_defaults(self) -> None:
        from corrections.derivation_schemas import ConflictCorrection

        cc = ConflictCorrection(
            conflict_id="abc" * 21 + "d",
            subject_id="e1",
            predicate="birthdate",
        )
        assert cc.status == "open"
        assert cc.resolution is None
        assert cc.competing_facts == []

    def test_conflict_correction_with_winner(self) -> None:
        from corrections.derivation_schemas import ConflictCorrection, ConflictResolution

        cc = ConflictCorrection(
            conflict_id="a" * 64,
            subject_id="e1",
            predicate="birthdate",
            resolution=ConflictResolution(winner="fact-id-abc"),
        )
        assert cc.resolution is not None
        assert cc.resolution.winner == "fact-id-abc"
        assert cc.resolution.coexist is False

    def test_conflict_resolution_coexist(self) -> None:
        from corrections.derivation_schemas import ConflictResolution

        cr = ConflictResolution(coexist=True)
        assert cr.coexist is True
        assert cr.winner is None

    def test_conflict_resolution_temporal_supersede(self) -> None:
        from corrections.derivation_schemas import ConflictResolution

        cr = ConflictResolution(temporal_supersede_order=["fact-old", "fact-new"])
        assert cr.temporal_supersede_order == ["fact-old", "fact-new"]


class TestConflictYAMLIO:
    def test_import(self) -> None:
        from corrections.conflict_io import emit_conflict_yaml, load_conflict_yaml  # noqa: F401

    def test_emit_creates_file(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import emit_conflict_yaml

        conflict = tmp_store.all_conflicts()[0]
        path = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        assert path.exists()

    def test_emit_file_under_conflicts_subdir(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import emit_conflict_yaml

        conflict = tmp_store.all_conflicts()[0]
        path = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        assert "conflicts" in str(path)

    def test_emit_yaml_contains_conflict_id(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import emit_conflict_yaml

        conflict = tmp_store.all_conflicts()[0]
        path = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        content = path.read_text()
        assert conflict.id in content

    def test_emit_yaml_contains_predicate(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import emit_conflict_yaml

        conflict = tmp_store.all_conflicts()[0]
        path = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        content = path.read_text()
        assert "birthdate" in content

    def test_emit_yaml_has_resolution_hints(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import emit_conflict_yaml

        conflict = tmp_store.all_conflicts()[0]
        path = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        content = path.read_text()
        assert "winner" in content

    def test_load_round_trips(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import emit_conflict_yaml, load_conflict_yaml

        conflict = tmp_store.all_conflicts()[0]
        path = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        loaded = load_conflict_yaml(path)
        assert loaded.conflict_id == conflict.id
        assert loaded.predicate == "birthdate"
        assert loaded.status == "open"

    def test_emit_idempotent(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import emit_conflict_yaml

        conflict = tmp_store.all_conflicts()[0]
        path1 = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        path2 = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        assert path1 == path2


class TestApplyConflictCorrections:
    def test_import(self) -> None:
        from corrections.conflict_io import apply_conflict_corrections  # noqa: F401

    def test_apply_winner_updates_store(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import (
            apply_conflict_corrections,
            emit_conflict_yaml,
            load_conflict_yaml,
        )
        from corrections.derivation_schemas import ConflictResolution

        conflict = tmp_store.all_conflicts()[0]
        winner_id = conflict.competing_fact_ids[0]
        path = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)

        # Manually add resolution to YAML (simulating human edit)
        cc = load_conflict_yaml(path)
        cc.status = "reviewed"
        cc.resolution = ConflictResolution(winner=winner_id)
        # Re-emit with resolution
        from corrections.conflict_io import write_conflict_yaml
        write_conflict_yaml(cc, path)

        changed = apply_conflict_corrections(tmp_corrections_root, tmp_store, apply=True)
        assert len(changed) == 1
        updated = tmp_store.get_conflict(conflict.id)
        assert updated is not None
        assert updated.status == "resolved_manually"
        assert updated.resolution is not None
        assert updated.resolution.get("winner") == winner_id

    def test_apply_dry_run_no_store_change(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import (
            apply_conflict_corrections,
            emit_conflict_yaml,
            load_conflict_yaml,
            write_conflict_yaml,
        )
        from corrections.derivation_schemas import ConflictResolution

        conflict = tmp_store.all_conflicts()[0]
        winner_id = conflict.competing_fact_ids[0]
        path = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        cc = load_conflict_yaml(path)
        cc.status = "reviewed"
        cc.resolution = ConflictResolution(winner=winner_id)
        write_conflict_yaml(cc, path)

        apply_conflict_corrections(tmp_corrections_root, tmp_store, apply=False)
        still_open = tmp_store.get_conflict(conflict.id)
        assert still_open is not None
        assert still_open.status == "open"

    def test_apply_coexist_resolves_manually(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import (
            apply_conflict_corrections,
            emit_conflict_yaml,
            load_conflict_yaml,
            write_conflict_yaml,
        )
        from corrections.derivation_schemas import ConflictResolution

        conflict = tmp_store.all_conflicts()[0]
        path = emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        cc = load_conflict_yaml(path)
        cc.status = "reviewed"
        cc.resolution = ConflictResolution(coexist=True)
        write_conflict_yaml(cc, path)

        apply_conflict_corrections(tmp_corrections_root, tmp_store, apply=True)
        updated = tmp_store.get_conflict(conflict.id)
        assert updated.status == "resolved_manually"
        assert updated.resolution.get("coexist") is True

    def test_apply_skips_unreviewed(
        self, tmp_corrections_root: Path, tmp_store: FactStore
    ) -> None:
        from corrections.conflict_io import apply_conflict_corrections, emit_conflict_yaml

        conflict = tmp_store.all_conflicts()[0]
        emit_conflict_yaml(conflict, tmp_store, tmp_corrections_root)
        # Status stays "open" — nothing reviewed
        changed = apply_conflict_corrections(tmp_corrections_root, tmp_store, apply=True)
        assert changed == []

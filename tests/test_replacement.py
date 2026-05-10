"""Phase 8b.1 (8.3) — `replaced_by` source-correction wiring.

When source-correction YAML carries `replaced_by: <other_doc_id>`,
facts derived from the older doc inherit a constrained valid_to
relative to the replacement, and Conflicts between old/new pairs
auto-resolve as resolved_temporally with the replacement as winner.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from corrections.io import save_source_correction
from corrections.schemas import SourceCorrection
from facts.models import Conflict, Fact
from facts.predicates import Predicate, PredicateRegistry
from facts.replacement import apply_replacements
from facts.store import FactStore


def _meta_json(*, document_id: str, document_date: str | None) -> str:
    """Minimal store metadata.json for a doc."""
    payload = {
        "document_id": document_id,
        "content_hash": "0" * 64,
        "original_filename": f"{document_id}.pdf",
        "original_path": f"/abs/{document_id}.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 10,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "docling_version": "test",
        "processing_duration_ms": 1,
        "source_type": "filesystem",
        "extraction_quality": "rich",
        "document_date": document_date,
        "doc_context": [],
    }
    import json
    return json.dumps(payload)


def _seed_doc(store_root: Path, document_id: str, *, document_date: str | None) -> None:
    d = store_root / document_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "metadata.json").write_text(
        _meta_json(document_id=document_id, document_date=document_date),
        encoding="utf-8",
    )


def _seed_correction(corrections_root: Path, *, doc_id: str, replaced_by: str | None) -> None:
    corr = SourceCorrection(
        document_id=doc_id,
        original_filename=f"{doc_id}.pdf",
        replaced_by=replaced_by,
    )
    save_source_correction(corrections_root, corr)


@pytest.fixture
def registry() -> PredicateRegistry:
    r = PredicateRegistry()
    r.register(Predicate(name="address", time_varying=True, allow_multi=False))
    r.register(Predicate(name="birthdate", time_varying=False, allow_multi=False))
    return r


# --- no-op cases -----------------------------------------------------------


def test_no_replacement_chains_no_change(tmp_path: Path, registry: PredicateRegistry) -> None:
    store = FactStore(tmp_path / "facts")
    f = Fact(
        subject_id="alice", predicate="address",
        canonical_value="Lyon", source_doc_id="doc-A",
        valid_from=date(2020, 1, 1),
    )
    store.append_fact(f)

    report = apply_replacements(
        store,
        corrections_root=tmp_path / "corrections",
        store_root=tmp_path / "store",
        registry=registry,
    )

    assert report.facts_updated == 0
    assert report.conflicts_resolved == 0
    assert store.get_fact(f.id).valid_to is None


def test_replacement_with_no_old_facts_noop(tmp_path: Path, registry: PredicateRegistry) -> None:
    store = FactStore(tmp_path / "facts")
    _seed_doc(tmp_path / "store", "doc-A", document_date=None)
    _seed_doc(tmp_path / "store", "doc-B", document_date="2023-06-01")
    _seed_correction(tmp_path / "corrections", doc_id="doc-A", replaced_by="doc-B")

    report = apply_replacements(
        store, corrections_root=tmp_path / "corrections",
        store_root=tmp_path / "store", registry=registry,
    )
    assert report.facts_updated == 0


# --- valid_to update on time_varying --------------------------------------


def test_replacement_sets_valid_to_from_new_fact_valid_from(
    tmp_path: Path, registry: PredicateRegistry,
) -> None:
    store = FactStore(tmp_path / "facts")
    _seed_doc(tmp_path / "store", "doc-A", document_date=None)
    _seed_doc(tmp_path / "store", "doc-B", document_date="2023-06-01")
    _seed_correction(tmp_path / "corrections", doc_id="doc-A", replaced_by="doc-B")

    old = Fact(
        subject_id="alice", predicate="address", canonical_value="Lyon",
        source_doc_id="doc-A", valid_from=date(2020, 1, 1),
    )
    new = Fact(
        subject_id="alice", predicate="address", canonical_value="Marseille",
        source_doc_id="doc-B", valid_from=date(2023, 6, 1),
    )
    store.append_fact(old)
    store.append_fact(new)

    report = apply_replacements(
        store, corrections_root=tmp_path / "corrections",
        store_root=tmp_path / "store", registry=registry,
    )

    assert report.facts_updated == 1
    refreshed = store.get_fact(old.id)
    assert refreshed.valid_to == date(2023, 5, 31)


def test_replacement_falls_back_to_doc_date_when_new_fact_undated(
    tmp_path: Path, registry: PredicateRegistry,
) -> None:
    store = FactStore(tmp_path / "facts")
    _seed_doc(tmp_path / "store", "doc-A", document_date=None)
    _seed_doc(tmp_path / "store", "doc-B", document_date="2023-06-01")
    _seed_correction(tmp_path / "corrections", doc_id="doc-A", replaced_by="doc-B")

    old = Fact(
        subject_id="alice", predicate="address", canonical_value="Lyon",
        source_doc_id="doc-A", valid_from=date(2020, 1, 1),
    )
    new = Fact(
        subject_id="alice", predicate="address", canonical_value="Marseille",
        source_doc_id="doc-B",  # no valid_from
    )
    store.append_fact(old)
    store.append_fact(new)

    report = apply_replacements(
        store, corrections_root=tmp_path / "corrections",
        store_root=tmp_path / "store", registry=registry,
    )

    assert report.facts_updated == 1
    assert store.get_fact(old.id).valid_to == date(2023, 5, 31)


def test_replacement_preserves_manual_valid_to(
    tmp_path: Path, registry: PredicateRegistry,
) -> None:
    store = FactStore(tmp_path / "facts")
    _seed_doc(tmp_path / "store", "doc-A", document_date=None)
    _seed_doc(tmp_path / "store", "doc-B", document_date="2023-06-01")
    _seed_correction(tmp_path / "corrections", doc_id="doc-A", replaced_by="doc-B")

    manual_to = date(2021, 12, 31)
    old = Fact(
        subject_id="alice", predicate="address", canonical_value="Lyon",
        source_doc_id="doc-A", valid_from=date(2020, 1, 1), valid_to=manual_to,
    )
    new = Fact(
        subject_id="alice", predicate="address", canonical_value="Marseille",
        source_doc_id="doc-B", valid_from=date(2023, 6, 1),
    )
    store.append_fact(old)
    store.append_fact(new)

    report = apply_replacements(
        store, corrections_root=tmp_path / "corrections",
        store_root=tmp_path / "store", registry=registry,
    )

    assert report.facts_updated == 0
    assert store.get_fact(old.id).valid_to == manual_to


def test_replacement_skips_time_invariant_valid_to(
    tmp_path: Path, registry: PredicateRegistry,
) -> None:
    """time_invariant facts (e.g. birthdate) don't get valid_to set; the
    Conflict still gets resolved if one exists."""
    store = FactStore(tmp_path / "facts")
    _seed_doc(tmp_path / "store", "doc-A", document_date=None)
    _seed_doc(tmp_path / "store", "doc-B", document_date="2023-06-01")
    _seed_correction(tmp_path / "corrections", doc_id="doc-A", replaced_by="doc-B")

    old = Fact(
        subject_id="alice", predicate="birthdate", canonical_value="1980-01-01",
        source_doc_id="doc-A",
    )
    new = Fact(
        subject_id="alice", predicate="birthdate", canonical_value="1981-01-01",
        source_doc_id="doc-B",
    )
    store.append_fact(old)
    store.append_fact(new)

    report = apply_replacements(
        store, corrections_root=tmp_path / "corrections",
        store_root=tmp_path / "store", registry=registry,
    )

    assert report.facts_updated == 0
    assert store.get_fact(old.id).valid_to is None


# --- conflict resolution ---------------------------------------------------


def test_replacement_resolves_competing_conflict(
    tmp_path: Path, registry: PredicateRegistry,
) -> None:
    store = FactStore(tmp_path / "facts")
    _seed_doc(tmp_path / "store", "doc-A", document_date=None)
    _seed_doc(tmp_path / "store", "doc-B", document_date="2023-06-01")
    _seed_correction(tmp_path / "corrections", doc_id="doc-A", replaced_by="doc-B")

    old = Fact(
        subject_id="alice", predicate="birthdate", canonical_value="1980-01-01",
        source_doc_id="doc-A",
    )
    new = Fact(
        subject_id="alice", predicate="birthdate", canonical_value="1981-01-01",
        source_doc_id="doc-B",
    )
    store.append_fact(old)
    store.append_fact(new)

    conflict = Conflict(
        subject_id="alice", predicate="birthdate",
        competing_fact_ids=[old.id, new.id], status="open",
    )
    store.append_conflict(conflict)

    report = apply_replacements(
        store, corrections_root=tmp_path / "corrections",
        store_root=tmp_path / "store", registry=registry,
    )

    assert report.conflicts_resolved == 1
    refreshed = store.get_conflict(conflict.id)
    assert refreshed.status == "resolved_temporally"
    assert refreshed.resolution is not None
    assert refreshed.resolution.get("winner_fact_id") == new.id
    assert refreshed.resolution.get("source") == "replaced_by"


def test_idempotent_second_run(tmp_path: Path, registry: PredicateRegistry) -> None:
    store = FactStore(tmp_path / "facts")
    _seed_doc(tmp_path / "store", "doc-A", document_date=None)
    _seed_doc(tmp_path / "store", "doc-B", document_date="2023-06-01")
    _seed_correction(tmp_path / "corrections", doc_id="doc-A", replaced_by="doc-B")

    old = Fact(
        subject_id="alice", predicate="address", canonical_value="Lyon",
        source_doc_id="doc-A", valid_from=date(2020, 1, 1),
    )
    new = Fact(
        subject_id="alice", predicate="address", canonical_value="Marseille",
        source_doc_id="doc-B", valid_from=date(2023, 6, 1),
    )
    store.append_fact(old)
    store.append_fact(new)

    report1 = apply_replacements(
        store, corrections_root=tmp_path / "corrections",
        store_root=tmp_path / "store", registry=registry,
    )
    assert report1.facts_updated == 1

    report2 = apply_replacements(
        store, corrections_root=tmp_path / "corrections",
        store_root=tmp_path / "store", registry=registry,
    )
    assert report2.facts_updated == 0

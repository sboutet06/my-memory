"""personal_documents pack — sanity checks on declared types + discovery."""
from __future__ import annotations

from pathlib import Path

from packs.registry import discover_packs


def test_pack_is_discovered() -> None:
    reg = discover_packs(Path("packs"))
    pack = reg.get("personal_documents")
    assert pack is not None
    assert pack.version
    assert pack.matches({}, "")


def test_declared_types_non_empty_and_lowercase() -> None:
    reg = discover_packs(Path("packs"))
    pack = reg.get("personal_documents")
    types = list(getattr(pack, "declared_types", []))
    assert len(types) >= 15, f"expected broad coverage, got {len(types)}"
    for t in types:
        assert t == t.lower(), f"non-lowercase declared type: {t!r}"


def test_expected_types_present() -> None:
    """Spot-check representative types across all life domains."""
    reg = discover_packs(Path("packs"))
    pack = reg.get("personal_documents")
    types = set(getattr(pack, "declared_types", []))
    for t in (
        "vehicle", "medication", "diagnosis", "ingredient",
        "event", "account", "role",
    ):
        assert t in types, f"missing expected type: {t!r}"


def test_no_collision_with_core_types() -> None:
    """Pack must not re-declare core types (they win already)."""
    from extraction.config import _DEFAULT_ENTITY_TYPES

    reg = discover_packs(Path("packs"))
    pack = reg.get("personal_documents")
    declared = set(getattr(pack, "declared_types", []))
    overlap = declared & set(_DEFAULT_ENTITY_TYPES)
    assert not overlap, f"pack redeclares core types: {overlap}"


def test_low_signal_types_declared() -> None:
    """Pack declares the retrieval-infra types core should hide."""
    reg = discover_packs(Path("packs"))
    pack = reg.get("personal_documents")
    low_sig = set(getattr(pack, "low_signal_types", ()))
    # Retrieval-infra types injected by the bank-statement pipeline.
    for t in ("transaction", "transaction_category", "account"):
        assert t in low_sig, f"expected {t} in low_signal_types"


def test_injector_hooks_exposed() -> None:
    """Pack routes structured extraction + summary extras via hooks."""
    reg = discover_packs(Path("packs"))
    pack = reg.get("personal_documents")
    assert callable(getattr(pack, "inject_structured", None))
    assert callable(getattr(pack, "summary_extras_for_doc", None))

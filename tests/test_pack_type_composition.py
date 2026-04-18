"""Compose entity types from core + pack-declared."""
from __future__ import annotations

from dataclasses import dataclass, field

from extraction.config import compose_entity_types


@dataclass
class _FakePack:
    name: str
    version: str = "0.1.0"
    declared_types: list[str] = field(default_factory=list)

    def matches(self, metadata, content_md):
        return False


def test_no_packs_returns_base() -> None:
    base = ["person", "organization"]
    assert compose_entity_types(base, []) == ["person", "organization"]


def test_pack_types_appended() -> None:
    base = ["person", "organization"]
    pack = _FakePack(name="p", declared_types=["medication", "ingredient"])
    assert compose_entity_types(base, [pack]) == [
        "person", "organization", "medication", "ingredient",
    ]


def test_pack_overlap_deduplicated_case_insensitive() -> None:
    base = ["person"]
    pack = _FakePack(name="p", declared_types=["Person", "MEDICATION", "medication"])
    # Core's exact casing is preserved; pack duplicates are dropped.
    assert compose_entity_types(base, [pack]) == ["person", "medication"]


def test_pack_without_declared_types_is_silent() -> None:
    @dataclass
    class _Minimal:
        name: str = "m"
        version: str = "0.1.0"

        def matches(self, m, c):
            return False

    base = ["person"]
    assert compose_entity_types(base, [_Minimal()]) == ["person"]


def test_multi_pack_order_preserved() -> None:
    base = ["core"]
    p1 = _FakePack(name="p1", declared_types=["a", "b"])
    p2 = _FakePack(name="p2", declared_types=["b", "c"])
    # p1 types before p2 types; b not duplicated.
    assert compose_entity_types(base, [p1, p2]) == ["core", "a", "b", "c"]

"""Unit tests for the pack framework (protocol + registry + discovery)."""
from __future__ import annotations

from pathlib import Path

import pytest

from packs import Pack, PackRegistry, discover_packs


class _FakePack:
    """Minimal pack for registry tests. Satisfies the Pack protocol."""
    name = "fake"
    version = "0.0.1"

    def __init__(self, match_names: list[str] | None = None) -> None:
        self._match_names = match_names or []

    def matches(self, metadata: dict, content_md: str) -> bool:
        fname = metadata.get("original_filename", "")
        return any(n in fname for n in self._match_names)


def test_pack_protocol_is_implemented_by_duck_type() -> None:
    p: Pack = _FakePack()  # type: ignore[assignment]  # Protocol check at call sites
    assert p.name == "fake"
    assert p.version == "0.0.1"


def test_registry_register_and_list() -> None:
    reg = PackRegistry()
    reg.register(_FakePack())
    assert [p.name for p in reg.list()] == ["fake"]


def test_registry_rejects_duplicate_name() -> None:
    reg = PackRegistry()
    reg.register(_FakePack())
    with pytest.raises(ValueError):
        reg.register(_FakePack())


def test_registry_resolve_by_name() -> None:
    reg = PackRegistry()
    fake = _FakePack()
    reg.register(fake)
    assert reg.get("fake") is fake
    assert reg.get("missing") is None


def test_resolve_for_doc_returns_first_matching() -> None:
    reg = PackRegistry()
    a = _FakePack()
    a.name = "a"
    a._match_names = ["RLV_CHQ"]
    b = _FakePack()
    b.name = "b"
    b._match_names = []
    reg.register(a)
    reg.register(b)

    meta = {"original_filename": "RLV_CHQ_20260326.pdf"}
    matched = reg.resolve_for_doc(meta, "")
    assert matched is a


def test_resolve_for_doc_returns_none_when_no_match() -> None:
    reg = PackRegistry()
    reg.register(_FakePack())
    assert reg.resolve_for_doc({"original_filename": "x.pdf"}, "") is None


# --- discovery ----------------------------------------------------------

def _write_pack(pack_dir: Path, name: str, body: str) -> None:
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "__init__.py").write_text(body, encoding="utf-8")


def test_discover_finds_pack_with_PACK_symbol(tmp_path: Path) -> None:
    pkg = tmp_path / "mypacks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    _write_pack(
        pkg / "demo_pack",
        "demo_pack",
        "class _P:\n"
        "    name = 'demo'\n"
        "    version = '1.0'\n"
        "    def matches(self, m, c): return False\n"
        "PACK = _P()\n",
    )

    reg = discover_packs(pkg)
    names = [p.name for p in reg.list()]
    assert names == ["demo"]


def test_discover_ignores_subdir_without_PACK(tmp_path: Path) -> None:
    pkg = tmp_path / "mypacks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    _write_pack(pkg / "not_a_pack", "not_a_pack", "x = 1\n")  # no PACK

    reg = discover_packs(pkg)
    assert reg.list() == []


def test_discover_ignores_missing_dir(tmp_path: Path) -> None:
    reg = discover_packs(tmp_path / "does-not-exist")
    assert reg.list() == []


def test_discover_skips_private_dirs(tmp_path: Path) -> None:
    """Dirs starting with `_` or `.` are framework-internal / hidden."""
    pkg = tmp_path / "mypacks"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    _write_pack(
        pkg / "_internal",
        "_internal",
        "class _P:\n"
        "    name='x'\n"
        "    version='0'\n"
        "    def matches(self,m,c): return False\n"
        "PACK=_P()\n",
    )
    _write_pack(
        pkg / ".hidden",
        ".hidden",
        "class _P:\n"
        "    name='h'\n"
        "    version='0'\n"
        "    def matches(self,m,c): return False\n"
        "PACK=_P()\n",
    )
    reg = discover_packs(pkg)
    assert reg.list() == []

"""PackRegistry + filesystem discovery."""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path

from packs.protocol import Pack

logger = logging.getLogger(__name__)


class PackRegistry:
    """In-memory registry of domain packs.

    Iteration order preserves registration order; `resolve_for_doc`
    returns the first-registered pack that claims the document.
    """

    def __init__(self) -> None:
        self._packs: list[Pack] = []

    def register(self, pack: Pack) -> None:
        if any(p.name == pack.name for p in self._packs):
            raise ValueError(f"pack already registered: {pack.name!r}")
        self._packs.append(pack)

    def list(self) -> list[Pack]:
        return list(self._packs)

    def get(self, name: str) -> Pack | None:
        for p in self._packs:
            if p.name == name:
                return p
        return None

    def resolve_for_doc(self, metadata: dict, content_md: str) -> Pack | None:
        for p in self._packs:
            try:
                if p.matches(metadata, content_md):
                    return p
            except Exception as exc:
                logger.warning("pack %r.matches() raised: %s", p.name, exc)
        return None


def _load_submodule_pack(packs_dir: Path, sub: Path) -> Pack | None:
    """Import `<packs_dir>/<sub>/__init__.py` and return its `PACK` if any."""
    init_file = sub / "__init__.py"
    if not init_file.is_file():
        return None
    # Use a unique module name so re-discovery from different roots doesn't
    # collide (tests use tmp dirs).
    module_name = f"_pack_discovery_{packs_dir.name}_{sub.name}"
    spec = importlib.util.spec_from_file_location(module_name, init_file)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.warning("pack %s failed to import: %s", sub.name, exc)
        return None
    pack = getattr(module, "PACK", None)
    if pack is None:
        return None
    # Soft protocol check — attribute access + callable `matches`.
    if not (hasattr(pack, "name") and hasattr(pack, "version") and callable(getattr(pack, "matches", None))):
        logger.warning("pack %s exports PACK but it doesn't satisfy the Pack protocol", sub.name)
        return None
    return pack


def discover_packs(packs_dir: Path) -> PackRegistry:
    """Scan `packs_dir` for subdirectories exposing a `PACK` symbol.

    Rules:
    - Only direct subdirectories are considered.
    - Dirs starting with `_` or `.` are ignored (framework-internal
      modules like `__pycache__`, hidden dirs).
    - A subdir is a pack if `<subdir>/__init__.py` exists and defines
      `PACK` implementing the `Pack` protocol.
    - Packs are registered in sorted-name order (deterministic).
    """
    reg = PackRegistry()
    if not packs_dir.exists():
        return reg
    subs = sorted(
        p for p in packs_dir.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    )
    for sub in subs:
        pack = _load_submodule_pack(packs_dir, sub)
        if pack is None:
            continue
        try:
            reg.register(pack)
        except ValueError as exc:
            logger.warning("pack %s already registered: %s", pack.name, exc)
    return reg

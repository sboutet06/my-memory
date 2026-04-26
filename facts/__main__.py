"""CLI entry point: python -m facts detect-conflicts."""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

from facts.detector import detect_all_conflicts
from facts.predicates import PredicateRegistry
from facts.store import FactStore
from facts.supersession import run_supersession
from packs import discover_packs


def _default_store_dir() -> Path:
    return Path(__file__).parent / "store"


def _build_registry() -> tuple[FactStore, PredicateRegistry]:
    store = FactStore(_default_store_dir())
    pack_registry = discover_packs(Path.cwd() / "packs")
    pred_registry = PredicateRegistry.from_packs(pack_registry.list())
    return store, pred_registry


def cmd_detect_conflicts() -> None:
    load_dotenv(Path.cwd() / ".env")
    store, pred_registry = _build_registry()
    conflicts = detect_all_conflicts(store, pred_registry)
    print(f"Detected {len(conflicts)} conflict(s).")
    for c in conflicts:
        print(f"  [{c.status}] subject={c.subject_id} predicate={c.predicate} "
              f"facts={len(c.competing_fact_ids)}")


def cmd_supersede() -> None:
    load_dotenv(Path.cwd() / ".env")
    store, pred_registry = _build_registry()
    changed = run_supersession(store, pred_registry)
    print(f"Supersession: closed valid_to on {changed} fact(s).")


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] == "detect-conflicts":
        cmd_detect_conflicts()
    elif args[0] == "supersede":
        cmd_supersede()
    else:
        print(f"Unknown command: {args[0]}", file=sys.stderr)
        print("Usage: python -m facts [detect-conflicts|supersede]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

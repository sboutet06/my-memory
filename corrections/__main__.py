"""CLI: inspect correction files across layers.

  python -m corrections review [--root PATH] [--all]
                              ↳ summary across source + derivation
  python -m corrections review source    [--all]
  python -m corrections review entity-types [--all]
  python -m corrections review aliases   [--all]
  python -m corrections show <slug-or-doc-id> [--root PATH]
  python -m corrections stats [--root PATH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from corrections.derivation_io import (
    ALIASES_SUBDIR,
    DERIVATION_SUBDIR,
    ENTITY_TYPES_SUBDIR,
    alias_path,
    entity_types_path,
    list_alias_corrections,
    list_entity_type_buckets,
)
from corrections.io import SOURCE_SUBDIR, correction_path, load_source_correction
from corrections.schemas import CorrectionStatus


# ------------------------------ listing ----------------------------------


def _list_source(root: Path, show_all: bool) -> list:
    source_dir = root / SOURCE_SUBDIR
    if not source_dir.is_dir():
        return []
    entries = []
    for y in sorted(source_dir.glob("*.yaml")):
        corr = load_source_correction(root, y.stem)
        if corr is None:
            continue
        if not show_all and corr.status != CorrectionStatus.PENDING:
            continue
        entries.append(corr)
    return entries


def _filter(items, show_all: bool):
    return [i for i in items if show_all or i.status == CorrectionStatus.PENDING]


# ---------------------------- review printers ---------------------------


def _print_source(corrs) -> None:
    if not corrs:
        print("  (none)")
        return
    for c in corrs:
        fields = ", ".join(d.field for d in c.doubts) or "-"
        print(f"  [{c.status.value}] {c.document_id}  ({c.original_filename})")
        print(f"      doubts: {fields}")


def _print_entity_types(buckets) -> None:
    if not buckets:
        print("  (none)")
        return
    for b in buckets:
        n_overrides = sum(1 for e in b.entries if e.override_type)
        print(f"  [{b.status.value}] {b.bucket}  "
              f"({len(b.entries)} entries, {n_overrides} overridden)")


def _print_aliases(corrs) -> None:
    if not corrs:
        print("  (none)")
        return
    for c in corrs:
        action = c.overrides.get("action") or "accept"
        print(f"  [{c.status.value}] {c.cluster}  "
              f"({len(c.members)} members, action={action})")


def _cmd_review(root: Path, layer: str | None, show_all: bool) -> int:
    source = _list_source(root, show_all)
    entity_types = _filter(list_entity_type_buckets(root), show_all)
    aliases = _filter(list_alias_corrections(root), show_all)

    total = len(source) + len(entity_types) + len(aliases)

    if layer in (None, "source"):
        if layer is None:
            print(f"== source ({len(source)}) ==")
        _print_source(source)
    if layer in (None, "entity-types"):
        if layer is None:
            print(f"\n== entity types ({len(entity_types)}) ==")
        _print_entity_types(entity_types)
    if layer in (None, "aliases"):
        if layer is None:
            print(f"\n== aliases ({len(aliases)}) ==")
        _print_aliases(aliases)

    if total == 0 and layer is None:
        print("No pending corrections.")
    elif layer is None:
        print(f"\nTotal: {total} pending correction(s).")
    return 0


# ------------------------------- show ------------------------------------


def _find_file(root: Path, slug_or_id: str) -> Path | None:
    for candidate in (
        correction_path(root, slug_or_id),
        entity_types_path(root, slug_or_id),
        alias_path(root, slug_or_id),
    ):
        if candidate.is_file():
            return candidate
    return None


def _cmd_show(root: Path, slug_or_id: str) -> int:
    p = _find_file(root, slug_or_id)
    if p is None:
        print(f"No correction file found for '{slug_or_id}' under {root}", file=sys.stderr)
        return 1
    print(f"# {p}")
    print(p.read_text(), end="")
    return 0


# ------------------------------- stats -----------------------------------


def _cmd_stats(root: Path) -> int:
    source_all = _list_source(root, show_all=True)
    et = list_entity_type_buckets(root)
    al = list_alias_corrections(root)

    def _by_status(items) -> dict:
        out = {"pending": 0, "reviewed": 0}
        for i in items:
            out[i.status.value] = out.get(i.status.value, 0) + 1
        return out

    print(f"source corrections:    {_by_status(source_all)}")
    print(f"entity-type buckets:   {_by_status(et)}  entries={sum(len(b.entries) for b in et)}")
    print(f"alias corrections:     {_by_status(al)}")
    return 0


# -------------------------------- main -----------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m corrections")
    sub = parser.add_subparsers(dest="cmd", required=True)

    review = sub.add_parser("review", help="List pending corrections")
    review.add_argument(
        "layer", nargs="?", choices=("source", "entity-types", "aliases"),
        help="Restrict to one layer (default: all)",
    )
    review.add_argument("--root", type=Path, default=Path("corrections"))
    review.add_argument("--all", action="store_true",
                        help="Include reviewed files")

    show = sub.add_parser("show", help="Print one correction file")
    show.add_argument("slug_or_id", help="document_id, bucket name, or alias cluster slug")
    show.add_argument("--root", type=Path, default=Path("corrections"))

    stats = sub.add_parser("stats", help="Counts per layer + status")
    stats.add_argument("--root", type=Path, default=Path("corrections"))

    args = parser.parse_args(argv)

    if args.cmd == "review":
        return _cmd_review(args.root, args.layer, args.all)
    if args.cmd == "show":
        return _cmd_show(args.root, args.slug_or_id)
    if args.cmd == "stats":
        return _cmd_stats(args.root)
    return 2


if __name__ == "__main__":
    sys.exit(main())

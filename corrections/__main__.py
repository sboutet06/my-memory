"""CLI: `python -m corrections review [--root PATH] [--all]`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from corrections.io import SOURCE_SUBDIR, load_source_correction
from corrections.schemas import CorrectionStatus


def _cmd_review(root: Path, show_all: bool) -> int:
    source_dir = root / SOURCE_SUBDIR
    if not source_dir.is_dir():
        print("No pending corrections.")
        return 0

    entries = []
    for yaml_path in sorted(source_dir.glob("*.yaml")):
        doc_id = yaml_path.stem
        corr = load_source_correction(root, doc_id)
        if corr is None:
            continue
        if not show_all and corr.status != CorrectionStatus.PENDING:
            continue
        entries.append(corr)

    if not entries:
        print("No pending corrections.")
        return 0

    for c in entries:
        fields = ", ".join(d.field for d in c.doubts) or "-"
        print(f"[{c.status.value}] {c.document_id}  ({c.original_filename})")
        print(f"  doubts: {fields}")

    print(f"\n{len(entries)} correction(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m corrections")
    sub = parser.add_subparsers(dest="cmd", required=True)

    review = sub.add_parser("review", help="List pending correction files")
    review.add_argument("--root", type=Path, default=Path("corrections"),
                        help="Corrections root (default: corrections/)")
    review.add_argument("--all", action="store_true",
                        help="Include reviewed files")

    args = parser.parse_args(argv)
    if args.cmd == "review":
        return _cmd_review(args.root, args.all)
    return 2


if __name__ == "__main__":
    sys.exit(main())

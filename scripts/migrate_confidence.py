#!/usr/bin/env python3
"""Phase 8b.2 — migrate `confidence: float` → `confidence: "deterministic|llm_high|llm_low"`.

All 17 existing facts + 17 claims as of 2026-05-10 are bank Transactions
with float confidence = 1.0 → all map to ConfidenceLevel.DETERMINISTIC.
The mapping rule for any future numeric stragglers (defensive):

    1.0           → deterministic
    0.5  ≤ x < 1  → llm_high
    < 0.5         → llm_low

Run from repo root:
    source venv/bin/activate
    python scripts/migrate_confidence.py [--apply]

Without --apply, prints the diff plan but does not write.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STORE = Path("facts/store")
TARGETS = ("facts.jsonl", "claims.jsonl")


def _categorize(v) -> str:
    if isinstance(v, str):
        return v  # already migrated
    if v == 1.0:
        return "deterministic"
    if v >= 0.5:
        return "llm_high"
    return "llm_low"


def _migrate_line(line: str) -> tuple[str, bool]:
    obj = json.loads(line)
    raw = obj.get("confidence")
    new = _categorize(raw)
    if new == raw:
        return line, False
    obj["confidence"] = new
    # `id` is a computed field — we don't store it, but the existing JSON
    # has it. confidence is NOT in the ID hash so the id stays the same.
    return json.dumps(obj, ensure_ascii=False), True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Write changes (default: dry-run).")
    args = p.parse_args(argv)

    total_lines = 0
    total_changed = 0

    for name in TARGETS:
        path = STORE / name
        if not path.is_file():
            print(f"skip: {path} absent")
            continue

        new_lines: list[str] = []
        changed = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            total_lines += 1
            new_line, was_changed = _migrate_line(line)
            if was_changed:
                changed += 1
            new_lines.append(new_line)
        total_changed += changed
        print(f"{path}: {changed}/{len(new_lines)} record(s) changed")

        if args.apply and changed:
            path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            print(f"  -> wrote {path}")

    print(f"\nTotal: {total_changed}/{total_lines} records.")
    if not args.apply:
        print("(dry-run; pass --apply to persist)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

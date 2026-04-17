"""CLI: `python -m evaluation [--cases PATH] [--store PATH] [--working-dir PATH]`."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from evaluation.runner import run_all, summarize
from evaluation.schema import load_cases
from extraction.graph import DEFAULT_WORKING_DIR


def _fmt_case(result) -> str:
    mark = "✓" if result.passed else "✗"
    return (
        f"  [{mark}] {result.case_id:<25} "
        f"doc={result.doc_coverage:.2f} "
        f"ent={result.entity_coverage:.2f} "
        f"fact={result.fact_coverage:.2f} "
        f"forbid={result.forbidden_violations}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation")
    parser.add_argument(
        "--cases", type=Path,
        default=Path(__file__).resolve().parent / "cases.json",
        help="Path to cases JSON file",
    )
    parser.add_argument("--store", type=Path, default=Path("store"))
    parser.add_argument("--working-dir", type=Path, default=DEFAULT_WORKING_DIR)
    parser.add_argument(
        "--json", action="store_true",
        help="Emit full JSON (otherwise summary + per-case one-liners).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cases = load_cases(args.cases)
    results = asyncio.run(run_all(cases, args.store, args.working_dir))
    summary = summarize(results)

    if args.json:
        print(json.dumps(
            {
                "summary": summary,
                "results": [r.model_dump() for r in results],
            },
            indent=2, ensure_ascii=False,
        ))
    else:
        print(f"\n=== Eval summary ({summary['passed']}/{summary['cases']} passed) ===")
        for r in results:
            print(_fmt_case(r))
        print()
        print(f"  mean doc_coverage   : {summary['mean_doc_coverage']:.2f}")
        print(f"  mean entity_coverage: {summary['mean_entity_coverage']:.2f}")
        print(f"  mean fact_coverage  : {summary['mean_fact_coverage']:.2f}")
        print(f"  forbidden violations: {summary['total_forbidden_violations']}")

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

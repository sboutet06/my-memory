"""CLI: `python -m evaluation [--cases PATH] [--store PATH] [--working-dir PATH]`."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from evaluation.aggregate import aggregate_runs
from evaluation.runner import build_doc_id_to_filename, run_all, run_all_multi, summarize
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


def _fmt_agg(agg) -> str:
    return (
        f"  {agg.case_id:<25} "
        f"pass={agg.pass_rate:.2f}  "
        f"doc={agg.mean_doc_coverage:.2f}±{agg.std_doc_coverage:.2f}  "
        f"ent={agg.mean_entity_coverage:.2f}±{agg.std_entity_coverage:.2f}  "
        f"fact={agg.mean_fact_coverage:.2f}±{agg.std_fact_coverage:.2f}"
    )


async def _run_diagnose(cases_path: Path, store_root: Path, working_dir: Path,
                        only_case: str | None) -> int:
    """Per-case retrieval trace — no LLM call, read-only.

    Shows, per eval case, which expected documents survive each retrieval
    stage (entity_vdb, chunks_vdb, relationships_vdb, rerank). Zero
    behavior change; pure instrumentation for Phase 5.1.
    """
    import json as _json
    from dotenv import load_dotenv

    from extraction.config import ExtractionConfig
    from extraction.diagnostics import trace_query
    from extraction.graph import build_rag

    load_dotenv(Path.cwd() / ".env")
    config = ExtractionConfig.from_env()
    config.require_api_key()

    cases = load_cases(cases_path)
    if only_case:
        cases = [c for c in cases if c.id == only_case]
        if not cases:
            print(f"No case with id={only_case!r}", file=sys.stderr)
            return 2

    id_to_filename = build_doc_id_to_filename(store_root)

    rag = await build_rag(working_dir=working_dir, config=config)
    reports = []
    try:
        for case in cases:
            trace = await trace_query(
                rag, case.question,
                expected_documents=list(case.expected_documents),
                id_to_filename=id_to_filename,
            )
            reports.append({
                "case_id": case.id,
                "question": case.question,
                "expected_documents": list(case.expected_documents),
                "stages": [
                    {
                        "stage": s.stage,
                        "hits": len(s.hits),
                        "expected_seen": s.expected_docs_seen,
                        "expected_missing": s.expected_docs_missing,
                    }
                    for s in trace.stages
                ],
            })
    finally:
        await rag.finalize_storages()

    print(_json.dumps({"cases": reports}, indent=2, ensure_ascii=False))
    return 0


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
        "--runs", type=int, default=1,
        help="Number of times to run each case (LLM cache cleared between runs) "
             "to measure retrieval/LLM variance (default: 1).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit full JSON (otherwise summary + per-case one-liners).",
    )
    parser.add_argument(
        "--diagnose", action="store_true",
        help="Retrieval-stage diagnostics mode: trace per-stage retention "
             "of expected_documents for each case. No LLM call, read-only.",
    )
    parser.add_argument(
        "--case", type=str, default=None,
        help="With --diagnose: only trace this case id.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.diagnose:
        return asyncio.run(_run_diagnose(
            args.cases, args.store, args.working_dir, args.case,
        ))

    cases = load_cases(args.cases)

    if args.runs <= 1:
        results = asyncio.run(run_all(cases, args.store, args.working_dir))
        summary = summarize(results)
        if args.json:
            print(json.dumps(
                {"summary": summary, "results": [r.model_dump() for r in results]},
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

    runs = asyncio.run(run_all_multi(cases, args.store, args.working_dir, args.runs))
    aggs = aggregate_runs(runs)
    if args.json:
        print(json.dumps(
            {
                "runs": args.runs,
                "aggregates": [a.model_dump() for a in aggs],
                "raw_runs": [[r.model_dump() for r in run] for run in runs],
            },
            indent=2, ensure_ascii=False,
        ))
    else:
        n_full_pass = sum(1 for a in aggs if a.pass_rate == 1.0)
        print(f"\n=== Eval summary over {args.runs} runs "
              f"({n_full_pass}/{len(aggs)} pass all runs) ===")
        for a in aggs:
            print(_fmt_agg(a))
        print()
        overall_doc = sum(a.mean_doc_coverage for a in aggs) / len(aggs) if aggs else 0.0
        overall_ent = sum(a.mean_entity_coverage for a in aggs) / len(aggs) if aggs else 0.0
        overall_fact = sum(a.mean_fact_coverage for a in aggs) / len(aggs) if aggs else 0.0
        print(f"  overall mean doc : {overall_doc:.2f}")
        print(f"  overall mean ent : {overall_ent:.2f}")
        print(f"  overall mean fact: {overall_fact:.2f}")
    return 0 if all(a.pass_rate == 1.0 for a in aggs) else 1


if __name__ == "__main__":
    sys.exit(main())

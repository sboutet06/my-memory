"""Run eval cases against the extraction query API. Needs live LLM."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from lightrag import QueryParam

from evaluation.schema import EvalCase, EvalCaseResult
from evaluation.scorer import (
    count_forbidden,
    score_conflict_detection_coverage,
    score_document_coverage,
    score_entity_coverage,
    score_fact_coverage,
    score_fact_provenance_coverage,
)
from extraction.config import ExtractionConfig
from extraction.graph import DEFAULT_WORKING_DIR, build_rag
from extraction.provenance import extract_document_ids
from extraction.references import (
    extract_references_from_query_result,
    inject_references,
)

logger = logging.getLogger(__name__)


def build_doc_id_to_filename(store_root: Path) -> dict[str, str]:
    """Read `store/*/metadata.json` → {doc_id: original_filename}."""
    mapping: dict[str, str] = {}
    if not store_root.exists():
        return mapping
    for entry in store_root.iterdir():
        if not entry.is_dir():
            continue
        meta_path = entry / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "document_id" in meta and "original_filename" in meta:
            mapping[meta["document_id"]] = meta["original_filename"]
    return mapping


def score_case(
    case: EvalCase,
    answer: str,
    cited_filenames: list[str],
) -> EvalCaseResult:
    doc = score_document_coverage(case.expected_documents, cited_filenames)
    ent = score_entity_coverage(case.expected_entities, answer)
    fac = score_fact_coverage(case.expected_facts, answer)
    fpc = score_fact_provenance_coverage(case.expected_provenance, answer)
    cdc = score_conflict_detection_coverage(case.expected_conflicts, answer)
    forbid = count_forbidden(case.forbidden_facts, answer)
    passed = (
        doc == 1.0 and ent == 1.0 and fac == 1.0 and fpc == 1.0
        and cdc == 1.0 and forbid == 0
    )
    return EvalCaseResult(
        case_id=case.id,
        question=case.question,
        mode=case.mode,
        answer=answer,
        document_ids=cited_filenames,
        doc_coverage=doc,
        entity_coverage=ent,
        fact_coverage=fac,
        fact_provenance_coverage=fpc,
        conflict_detection_coverage=cdc,
        forbidden_violations=forbid,
        passed=passed,
    )


async def run_case(
    rag,
    case: EvalCase,
    id_to_filename: dict[str, str],
    config: ExtractionConfig,
) -> EvalCaseResult:
    # Use aquery_llm to get LightRAG's authoritative reference list
    # alongside the answer; rewrite the answer's References block into a
    # canonical `/store/<uuid>/content.md` form so the provenance regex
    # can always parse it. This is deterministic and LLM-agnostic;
    # see Phase 5.3b in docs/intent.md.
    result = await rag.aquery_llm(
        case.question,
        param=QueryParam(
            mode=case.mode,
            user_prompt=config.temporal_user_prompt,
        ),
    )
    llm_resp = result.get("llm_response") or {}
    answer = llm_resp.get("content") or ""
    refs = extract_references_from_query_result(result)
    answer = inject_references(answer, refs)

    cited_ids = extract_document_ids(answer)
    cited_filenames = [id_to_filename.get(i, i) for i in cited_ids]
    return score_case(case, answer, cited_filenames)


_LLM_CACHE_FILE = "kv_store_llm_response_cache.json"


def _clear_llm_cache(working_dir: Path) -> None:
    """Delete LightRAG's LLM response cache. Forces fresh LLM calls next run."""
    cache_file = working_dir / _LLM_CACHE_FILE
    if cache_file.is_file():
        cache_file.unlink()


async def run_all(
    cases: Iterable[EvalCase],
    store_root: Path,
    working_dir: Path,
    config: ExtractionConfig | None = None,
) -> list[EvalCaseResult]:
    if config is None:
        load_dotenv(Path.cwd() / ".env")
        config = ExtractionConfig.from_env()
        config.require_api_key()

    id_to_filename = build_doc_id_to_filename(store_root)
    if not id_to_filename:
        raise SystemExit(f"No ingested docs at {store_root}")
    if not working_dir.exists():
        raise SystemExit(f"No extraction store at {working_dir}. Run `extract` first.")

    rag = await build_rag(working_dir=working_dir, config=config)
    results: list[EvalCaseResult] = []
    try:
        for case in cases:
            logger.info("Running %s: %s", case.id, case.question[:60])
            result = await run_case(rag, case, id_to_filename, config)
            results.append(result)
    finally:
        await rag.finalize_storages()
    return results


async def run_all_multi(
    cases: list[EvalCase],
    store_root: Path,
    working_dir: Path,
    n_runs: int,
) -> list[list[EvalCaseResult]]:
    """Run the full case list `n_runs` times with a cold LLM cache each time.

    Same order each run (matches `aggregate_runs`'s alignment contract).
    """
    if n_runs < 1:
        raise ValueError("n_runs must be >= 1")
    runs: list[list[EvalCaseResult]] = []
    for i in range(n_runs):
        logger.info("eval run %d/%d", i + 1, n_runs)
        _clear_llm_cache(working_dir)
        runs.append(await run_all(cases, store_root, working_dir))
    return runs


def summarize(results: list[EvalCaseResult]) -> dict:
    if not results:
        return {"cases": 0}
    n = len(results)
    return {
        "cases": n,
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "mean_doc_coverage": sum(r.doc_coverage for r in results) / n,
        "mean_entity_coverage": sum(r.entity_coverage for r in results) / n,
        "mean_fact_coverage": sum(r.fact_coverage for r in results) / n,
        "total_forbidden_violations": sum(r.forbidden_violations for r in results),
    }

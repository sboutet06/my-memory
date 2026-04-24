"""Multi-model benchmark runner.

Only the `query_answerer` stage is supported: the RAG query LLM is swapped
per model_id while the extraction graph stays fixed.
"""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

from evaluation.runner import run_all, summarize
from evaluation.schema import EvalCase
from extraction.config import ExtractionConfig

from benchmarks.schema import BenchmarkResult

logger = logging.getLogger(__name__)

_SUPPORTED_STAGES = frozenset({"query_answerer"})


async def run(
    stage: str,
    model_list: list[str],
    cases: list[EvalCase],
    store_root: Path,
    working_dir: Path,
    base_config: ExtractionConfig | None = None,
    case_limit: int | None = None,
) -> list[BenchmarkResult]:
    """Run the eval pipeline once per model, swapping the targeted stage LLM.

    Args:
        stage: Pipeline stage to benchmark. Currently only ``"query_answerer"``.
        model_list: OpenRouter model IDs to benchmark in order.
        cases: Gold-standard eval cases to run.
        store_root: Path to the ingested document store (``store/``).
        working_dir: LightRAG working directory (``extraction/``).
        base_config: Base extraction config. Defaults to ``ExtractionConfig()``.
            The ``llm_model`` field is swapped per iteration; the original is
            never mutated.
        case_limit: Slice cases to this length before running. ``None`` = all.

    Returns:
        One :class:`BenchmarkResult` per model, in ``model_list`` order.
    """
    if stage not in _SUPPORTED_STAGES:
        raise ValueError(
            f"Unknown stage: {stage!r}. Supported: {sorted(_SUPPORTED_STAGES)}"
        )

    if base_config is None:
        base_config = ExtractionConfig()

    sliced = cases[:case_limit] if case_limit is not None else cases

    results: list[BenchmarkResult] = []
    for model_id in model_list:
        cfg = dataclasses.replace(base_config, llm_model=model_id)
        logger.info("benchmark stage=%s model=%s n_cases=%d", stage, model_id, len(sliced))
        run_results = await run_all(
            cases=sliced,
            store_root=store_root,
            working_dir=working_dir,
            config=cfg,
        )
        summary = summarize(run_results)
        results.append(BenchmarkResult(
            model_id=model_id,
            stage=stage,
            n_cases=len(run_results),
            summary=summary,
            run_results=run_results,
        ))

    return results

"""Smoke tests for the benchmark scaffolding (task 6.6).

No real LLM calls — run_all is mocked.
"""
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from evaluation.schema import EvalCase, EvalCaseResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_case(case_id: str = "c1") -> EvalCase:
    return EvalCase(id=case_id, question="Test?")


def _make_result(case_id: str = "c1", model_id: str = "m1") -> EvalCaseResult:
    return EvalCaseResult(
        case_id=case_id,
        question="Test?",
        mode="hybrid",
        answer=f"Answer from {model_id}",
        document_ids=[],
        doc_coverage=1.0,
        entity_coverage=1.0,
        fact_coverage=1.0,
        fact_provenance_coverage=1.0,
        forbidden_violations=0,
        passed=True,
    )


# ---------------------------------------------------------------------------
# schema tests
# ---------------------------------------------------------------------------

class TestBenchmarkResult:
    def test_import(self):
        from benchmarks.schema import BenchmarkResult  # noqa: F401

    def test_fields(self):
        from benchmarks.schema import BenchmarkResult
        br = BenchmarkResult(
            model_id="google/gemini-2.5-flash",
            stage="query_answerer",
            n_cases=1,
            summary={"passed": 1},
            run_results=[_make_result()],
        )
        assert br.model_id == "google/gemini-2.5-flash"
        assert br.stage == "query_answerer"
        assert br.n_cases == 1
        assert br.summary == {"passed": 1}
        assert len(br.run_results) == 1

    def test_is_dataclass(self):
        from benchmarks.schema import BenchmarkResult
        assert dataclasses.is_dataclass(BenchmarkResult)


# ---------------------------------------------------------------------------
# runner import + interface tests
# ---------------------------------------------------------------------------

class TestBenchmarkRunnerImport:
    def test_import_run(self):
        from benchmarks.runner import run  # noqa: F401

    def test_unknown_stage_raises(self):
        from benchmarks.runner import run
        with pytest.raises(ValueError, match="query_answerer"):
            asyncio.get_event_loop().run_until_complete(
                run(
                    stage="extractor",
                    model_list=["m1"],
                    cases=[_make_case()],
                    store_root=Path("/tmp"),
                    working_dir=Path("/tmp"),
                )
            )


# ---------------------------------------------------------------------------
# Smoke test: 1 case × 1 model, run_all mocked
# ---------------------------------------------------------------------------

class TestBenchmarkSmoke:
    def test_smoke_one_case_one_model(self, tmp_path):
        """BenchmarkResult wraps run_all output without mutation."""
        from benchmarks.runner import run

        case = _make_case("smoke")
        expected_result = _make_result("smoke", "google/gemini-2.5-flash")

        async def _go():
            with patch(
                "benchmarks.runner.run_all",
                new=AsyncMock(return_value=[expected_result]),
            ):
                results = await run(
                    stage="query_answerer",
                    model_list=["google/gemini-2.5-flash"],
                    cases=[case],
                    store_root=tmp_path,
                    working_dir=tmp_path,
                )
            return results

        results = asyncio.get_event_loop().run_until_complete(_go())

        assert len(results) == 1
        br = results[0]
        assert br.model_id == "google/gemini-2.5-flash"
        assert br.stage == "query_answerer"
        assert br.n_cases == 1
        assert br.run_results == [expected_result]

    def test_smoke_case_limit(self, tmp_path):
        """case_limit slices the case list before passing to run_all."""
        from benchmarks.runner import run

        cases = [_make_case(f"c{i}") for i in range(5)]
        results_for_2 = [_make_result(f"c{i}") for i in range(2)]

        async def _go():
            with patch(
                "benchmarks.runner.run_all",
                new=AsyncMock(return_value=results_for_2),
            ) as mock_run:
                await run(
                    stage="query_answerer",
                    model_list=["m1"],
                    cases=cases,
                    store_root=tmp_path,
                    working_dir=tmp_path,
                    case_limit=2,
                )
                # run_all must have received only 2 cases
                call_cases = mock_run.call_args.kwargs.get(
                    "cases"
                ) or mock_run.call_args.args[0]
                assert len(list(call_cases)) == 2

        asyncio.get_event_loop().run_until_complete(_go())

    def test_smoke_multi_model(self, tmp_path):
        """One BenchmarkResult per model."""
        from benchmarks.runner import run

        case = _make_case()
        call_order: list[str] = []

        async def _fake_run_all(cases, store_root, working_dir, config=None):
            call_order.append(config.llm_model if config else "none")
            return [_make_result("c1", config.llm_model if config else "none")]

        async def _go():
            with patch("benchmarks.runner.run_all", new=_fake_run_all):
                return await run(
                    stage="query_answerer",
                    model_list=["m1", "m2"],
                    cases=[case],
                    store_root=tmp_path,
                    working_dir=tmp_path,
                )

        results = asyncio.get_event_loop().run_until_complete(_go())
        assert len(results) == 2
        assert {r.model_id for r in results} == {"m1", "m2"}
        assert call_order == ["m1", "m2"]

    def test_smoke_config_swap_does_not_mutate_original(self, tmp_path):
        """run() must not mutate the caller's config."""
        from benchmarks.runner import run
        from extraction.config import ExtractionConfig

        original_model = "original/model"
        cfg = ExtractionConfig(llm_model=original_model)

        async def _go():
            with patch(
                "benchmarks.runner.run_all",
                new=AsyncMock(return_value=[_make_result()]),
            ):
                await run(
                    stage="query_answerer",
                    model_list=["swapped/model"],
                    cases=[_make_case()],
                    store_root=tmp_path,
                    working_dir=tmp_path,
                    base_config=cfg,
                )

        asyncio.get_event_loop().run_until_complete(_go())
        assert cfg.llm_model == original_model

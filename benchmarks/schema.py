"""Benchmark result schema."""
from __future__ import annotations

from dataclasses import dataclass, field

from evaluation.schema import EvalCaseResult


@dataclass
class BenchmarkResult:
    model_id: str
    stage: str
    n_cases: int
    summary: dict
    run_results: list[EvalCaseResult] = field(default_factory=list)

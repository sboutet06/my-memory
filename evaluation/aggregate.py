"""Aggregate multi-run eval results into mean/std/pass_rate per case."""
from __future__ import annotations

import math
from statistics import mean, pstdev

from pydantic import BaseModel

from evaluation.schema import EvalCaseResult


class AggregatedCaseResult(BaseModel):
    case_id: str
    question: str
    runs: int
    pass_rate: float  # fraction of runs with passed==True

    mean_doc_coverage: float
    std_doc_coverage: float

    mean_entity_coverage: float
    std_entity_coverage: float

    mean_fact_coverage: float
    std_fact_coverage: float

    mean_fact_provenance_coverage: float
    std_fact_provenance_coverage: float

    mean_conflict_detection_coverage: float
    std_conflict_detection_coverage: float

    mean_temporal_accuracy: float
    std_temporal_accuracy: float

    mean_abstention_accuracy: float
    std_abstention_accuracy: float

    mean_forbidden_violations: float


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], 0.0
    m = mean(values)
    s = pstdev(values)  # population stddev — we ARE the whole sample
    if math.isnan(s):
        s = 0.0
    return m, s


def aggregate_runs(runs: list[list[EvalCaseResult]]) -> list[AggregatedCaseResult]:
    """Transpose `runs[i][c]` into per-case aggregates.

    Each run must contain the same case_ids in the same order (the runner
    preserves order). Raises `ValueError` if not.
    """
    if not runs:
        return []
    n_runs = len(runs)
    n_cases = len(runs[0])
    # Check alignment
    for r_idx, run in enumerate(runs):
        if len(run) != n_cases:
            raise ValueError(f"run {r_idx} has {len(run)} cases, expected {n_cases}")
        for c_idx, case in enumerate(run):
            if case.case_id != runs[0][c_idx].case_id:
                raise ValueError(
                    f"case_id mismatch at run {r_idx} case {c_idx}: "
                    f"{case.case_id!r} != {runs[0][c_idx].case_id!r}"
                )

    out: list[AggregatedCaseResult] = []
    for c_idx in range(n_cases):
        samples = [runs[r][c_idx] for r in range(n_runs)]
        doc_m, doc_s = _mean_std([s.doc_coverage for s in samples])
        ent_m, ent_s = _mean_std([s.entity_coverage for s in samples])
        fact_m, fact_s = _mean_std([s.fact_coverage for s in samples])
        fpc_m, fpc_s = _mean_std([s.fact_provenance_coverage for s in samples])
        cdc_m, cdc_s = _mean_std([s.conflict_detection_coverage for s in samples])
        ta_m, ta_s = _mean_std([s.temporal_accuracy for s in samples])
        aa_m, aa_s = _mean_std([s.abstention_accuracy for s in samples])
        forbid_m, _ = _mean_std([float(s.forbidden_violations) for s in samples])
        pass_rate = sum(1 for s in samples if s.passed) / n_runs
        out.append(AggregatedCaseResult(
            case_id=samples[0].case_id,
            question=samples[0].question,
            runs=n_runs,
            pass_rate=pass_rate,
            mean_doc_coverage=doc_m,
            std_doc_coverage=doc_s,
            mean_entity_coverage=ent_m,
            std_entity_coverage=ent_s,
            mean_fact_coverage=fact_m,
            std_fact_coverage=fact_s,
            mean_fact_provenance_coverage=fpc_m,
            std_fact_provenance_coverage=fpc_s,
            mean_conflict_detection_coverage=cdc_m,
            std_conflict_detection_coverage=cdc_s,
            mean_temporal_accuracy=ta_m,
            std_temporal_accuracy=ta_s,
            mean_abstention_accuracy=aa_m,
            std_abstention_accuracy=aa_s,
            mean_forbidden_violations=forbid_m,
        ))
    return out

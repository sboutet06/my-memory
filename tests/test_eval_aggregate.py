"""Tests for multi-run aggregation."""
from __future__ import annotations

from evaluation.aggregate import AggregatedCaseResult, aggregate_runs
from evaluation.schema import EvalCaseResult


def _result(case_id: str, doc: float, ent: float, fact: float, forbid: int, passed: bool) -> EvalCaseResult:
    return EvalCaseResult(
        case_id=case_id,
        question="q",
        mode="hybrid",
        answer="a",
        document_ids=[],
        doc_coverage=doc,
        entity_coverage=ent,
        fact_coverage=fact,
        forbidden_violations=forbid,
        passed=passed,
    )


def test_single_run_stats() -> None:
    runs = [[_result("c1", 1.0, 1.0, 1.0, 0, True)]]
    aggs = aggregate_runs(runs)
    assert len(aggs) == 1
    a = aggs[0]
    assert a.case_id == "c1"
    assert a.runs == 1
    assert a.pass_rate == 1.0
    assert a.mean_doc_coverage == 1.0
    assert a.std_doc_coverage == 0.0


def test_multi_run_mean_std() -> None:
    runs = [
        [_result("c1", 1.0, 1.0, 1.0, 0, True)],
        [_result("c1", 0.0, 0.5, 0.5, 1, False)],
    ]
    aggs = aggregate_runs(runs)
    a = aggs[0]
    assert a.runs == 2
    assert a.pass_rate == 0.5
    assert a.mean_doc_coverage == 0.5
    # stddev of [1.0, 0.0] population is 0.5
    assert abs(a.std_doc_coverage - 0.5) < 1e-9
    assert a.mean_forbidden_violations == 0.5


def test_multiple_cases_preserved() -> None:
    runs = [
        [
            _result("c1", 1.0, 1.0, 1.0, 0, True),
            _result("c2", 0.5, 0.5, 0.5, 0, False),
        ],
        [
            _result("c1", 0.0, 0.0, 0.0, 0, False),
            _result("c2", 0.5, 0.5, 0.5, 0, False),
        ],
    ]
    aggs = aggregate_runs(runs)
    assert [a.case_id for a in aggs] == ["c1", "c2"]
    c1, c2 = aggs
    assert c1.pass_rate == 0.5
    assert c2.pass_rate == 0.0
    assert c2.std_doc_coverage == 0.0  # identical across runs


def test_mismatched_case_ids_raises() -> None:
    runs = [
        [_result("c1", 1.0, 1.0, 1.0, 0, True)],
        [_result("c2", 1.0, 1.0, 1.0, 0, True)],
    ]
    import pytest
    with pytest.raises(ValueError):
        aggregate_runs(runs)


def test_empty_runs_empty_output() -> None:
    assert aggregate_runs([]) == []

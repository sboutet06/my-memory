"""Tests for temporal_accuracy metric — Phase 8.6.

Substring-coverage scoring against expected_temporal strings, same
accent-insensitive OR-alt semantics as fact_coverage.
"""
from __future__ import annotations

import pytest


class TestTemporalAccuracyScorer:
    def test_import(self) -> None:
        from evaluation.scorer import score_temporal_accuracy  # noqa: F401

    def test_empty_expected_returns_1(self) -> None:
        from evaluation.scorer import score_temporal_accuracy

        assert score_temporal_accuracy([], "any answer") == 1.0

    def test_full_match(self) -> None:
        from evaluation.scorer import score_temporal_accuracy

        answer = "In 2017 the address was 20 rue B; before 2015 it was 10 rue A."
        score = score_temporal_accuracy(["20 rue B", "10 rue A"], answer)
        assert score == 1.0

    def test_partial_match(self) -> None:
        from evaluation.scorer import score_temporal_accuracy

        score = score_temporal_accuracy(["20 rue B", "30 rue C"], "Currently 20 rue B.")
        assert score == 0.5

    def test_accent_insensitive(self) -> None:
        from evaluation.scorer import score_temporal_accuracy

        score = score_temporal_accuracy(["Rue de l'Étoile"], "Lives at rue de l'etoile.")
        assert score == 1.0


class TestEvalCaseExpectedTemporal:
    def test_field_exists_with_default(self) -> None:
        from evaluation.schema import EvalCase

        case = EvalCase(id="x", question="q")
        assert case.expected_temporal == []

    def test_field_accepts_list(self) -> None:
        from evaluation.schema import EvalCase

        case = EvalCase(
            id="t1",
            question="Quelle adresse en 2017 ?",
            expected_temporal=["20 rue B"],
        )
        assert case.expected_temporal == ["20 rue B"]


class TestEvalCaseResultTemporalAccuracy:
    def test_field_exists_with_default(self) -> None:
        from evaluation.schema import EvalCaseResult

        r = EvalCaseResult(
            case_id="x",
            question="q",
            mode="hybrid",
            answer="a",
            document_ids=[],
            doc_coverage=1.0,
            entity_coverage=1.0,
            fact_coverage=1.0,
            fact_provenance_coverage=1.0,
            forbidden_violations=0,
            passed=True,
        )
        assert r.temporal_accuracy == 1.0


class TestRunnerWiring:
    def test_score_case_uses_temporal_accuracy(self) -> None:
        from evaluation.runner import score_case
        from evaluation.schema import EvalCase

        case = EvalCase(
            id="t1",
            question="Quelle adresse en 2017 ?",
            expected_temporal=["20 rue B", "30 rue C"],
        )
        result = score_case(case, "Currently 20 rue B.", [])
        assert result.temporal_accuracy == 0.5
        assert result.passed is False

    def test_score_case_full_temporal_pass(self) -> None:
        from evaluation.runner import score_case
        from evaluation.schema import EvalCase

        case = EvalCase(
            id="t1",
            question="Adresses au cours du temps ?",
            expected_temporal=["10 rue A", "20 rue B"],
        )
        result = score_case(
            case, "From 2010 to 2014: 10 rue A. From 2015: 20 rue B.", [],
        )
        assert result.temporal_accuracy == 1.0
        assert result.passed is True


class TestAggregateWiring:
    def test_aggregate_includes_temporal_accuracy(self) -> None:
        from evaluation.aggregate import aggregate_runs
        from evaluation.schema import EvalCaseResult

        def _r(ta: float) -> EvalCaseResult:
            return EvalCaseResult(
                case_id="c1",
                question="q",
                mode="hybrid",
                answer="a",
                document_ids=[],
                doc_coverage=1.0,
                entity_coverage=1.0,
                fact_coverage=1.0,
                fact_provenance_coverage=1.0,
                conflict_detection_coverage=1.0,
                temporal_accuracy=ta,
                forbidden_violations=0,
                passed=ta == 1.0,
            )

        agg = aggregate_runs([[_r(0.5)], [_r(1.0)]])
        assert hasattr(agg[0], "mean_temporal_accuracy")
        assert abs(agg[0].mean_temporal_accuracy - 0.75) < 1e-9

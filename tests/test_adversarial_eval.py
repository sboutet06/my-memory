"""Tests for adversarial eval bucket — conflict_detection_coverage metric.

TDD: these fail until scorer/schema/runner/aggregate are updated.
"""
from __future__ import annotations

import pytest


class TestConflictDetectionScorer:
    def test_import(self) -> None:
        from evaluation.scorer import score_conflict_detection_coverage  # noqa: F401

    def test_empty_expected_returns_1(self) -> None:
        from evaluation.scorer import score_conflict_detection_coverage

        assert score_conflict_detection_coverage([], "any answer") == 1.0

    def test_all_conflicts_present_returns_1(self) -> None:
        from evaluation.scorer import score_conflict_detection_coverage

        answer = "Jean Dupont's birthdate is either 1980-01-15 or 1982-03-22, sources disagree."
        score = score_conflict_detection_coverage(
            ["1980-01-15", "1982-03-22"], answer
        )
        assert score == 1.0

    def test_only_one_value_present_returns_0_5(self) -> None:
        from evaluation.scorer import score_conflict_detection_coverage

        answer = "Jean Dupont was born on 1980-01-15."
        score = score_conflict_detection_coverage(
            ["1980-01-15", "1982-03-22"], answer
        )
        assert score == 0.5

    def test_neither_value_present_returns_0(self) -> None:
        from evaluation.scorer import score_conflict_detection_coverage

        answer = "No information found about this person."
        score = score_conflict_detection_coverage(
            ["1980-01-15", "1982-03-22"], answer
        )
        assert score == 0.0

    def test_accent_insensitive(self) -> None:
        from evaluation.scorer import score_conflict_detection_coverage

        score = score_conflict_detection_coverage(
            ["Zoé"], "The answer mentions Zoe as the name."
        )
        assert score == 1.0

    def test_or_alternatives(self) -> None:
        from evaluation.scorer import score_conflict_detection_coverage

        score = score_conflict_detection_coverage(
            ["1980|nineteen-eighty"], "Born in nineteen-eighty according to one doc."
        )
        assert score == 1.0


class TestEvalCaseSchema:
    def test_expected_conflicts_field_exists(self) -> None:
        from evaluation.schema import EvalCase

        case = EvalCase(id="x", question="q")
        assert hasattr(case, "expected_conflicts")
        assert case.expected_conflicts == []

    def test_expected_conflicts_accepts_list(self) -> None:
        from evaluation.schema import EvalCase

        case = EvalCase(
            id="adversarial-birthdate",
            question="Quelle est la date de naissance ?",
            expected_conflicts=["1980-01-15", "1982-03-22"],
        )
        assert len(case.expected_conflicts) == 2


class TestEvalCaseResultSchema:
    def test_conflict_detection_coverage_field_exists(self) -> None:
        from evaluation.schema import EvalCaseResult

        result = EvalCaseResult(
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
        assert hasattr(result, "conflict_detection_coverage")
        assert result.conflict_detection_coverage == 1.0

    def test_conflict_detection_coverage_in_passed_check(self) -> None:
        from evaluation.schema import EvalCaseResult

        # cdc < 1.0 → passed must be False
        result = EvalCaseResult(
            case_id="x",
            question="q",
            mode="hybrid",
            answer="a",
            document_ids=[],
            doc_coverage=1.0,
            entity_coverage=1.0,
            fact_coverage=1.0,
            fact_provenance_coverage=1.0,
            conflict_detection_coverage=0.5,
            forbidden_violations=0,
            passed=False,
        )
        assert result.passed is False


class TestRunnerWiring:
    def test_score_case_uses_conflict_detection_coverage(self) -> None:
        from evaluation.runner import score_case
        from evaluation.schema import EvalCase

        case = EvalCase(
            id="adv-test",
            question="Quelle est la date de naissance ?",
            expected_conflicts=["1980-01-15", "1982-03-22"],
        )
        # Answer contains only one value → cdc = 0.5 → not passed
        result = score_case(case, "Born on 1980-01-15 per doc A.", [])
        assert result.conflict_detection_coverage == 0.5
        assert result.passed is False

    def test_score_case_full_conflict_match(self) -> None:
        from evaluation.runner import score_case
        from evaluation.schema import EvalCase

        case = EvalCase(
            id="adv-test",
            question="Conflit de date de naissance ?",
            expected_conflicts=["1980-01-15", "1982-03-22"],
        )
        answer = "Conflict found: 1980-01-15 in doc A vs 1982-03-22 in doc B."
        result = score_case(case, answer, [])
        assert result.conflict_detection_coverage == 1.0
        assert result.passed is True

    def test_score_case_no_expected_conflicts_defaults_1(self) -> None:
        from evaluation.runner import score_case
        from evaluation.schema import EvalCase

        case = EvalCase(id="normal", question="Normal question")
        result = score_case(case, "Some answer.", [])
        assert result.conflict_detection_coverage == 1.0


class TestAggregateWiring:
    def test_aggregate_includes_conflict_detection_coverage(self) -> None:
        from evaluation.aggregate import AggregatedCaseResult, aggregate_runs
        from evaluation.schema import EvalCaseResult

        def _result(cdc: float) -> EvalCaseResult:
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
                conflict_detection_coverage=cdc,
                forbidden_violations=0,
                passed=cdc == 1.0,
            )

        runs = [[_result(0.5)], [_result(1.0)]]
        agg = aggregate_runs(runs)
        assert len(agg) == 1
        assert hasattr(agg[0], "mean_conflict_detection_coverage")
        assert abs(agg[0].mean_conflict_detection_coverage - 0.75) < 1e-9

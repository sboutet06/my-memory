"""Task 6.5 — fact_provenance_coverage metric and schema extensions.

Covers: new scorer function, expected_provenance field on EvalCase,
fact_provenance_coverage field on EvalCaseResult, backward-compat
(existing cases with no expected_provenance score 1.0).
"""
from __future__ import annotations

import pytest

from evaluation.schema import EvalCase, EvalCaseResult
from evaluation.scorer import score_fact_provenance_coverage


class TestScoreFactProvenanceCoverage:
    def test_empty_expected_returns_perfect(self) -> None:
        assert score_fact_provenance_coverage([], "any answer text") == 1.0

    def test_present_string_scores_1(self) -> None:
        assert score_fact_provenance_coverage(["virement"], "virement entrant détecté") == 1.0

    def test_absent_string_scores_0(self) -> None:
        assert score_fact_provenance_coverage(["virement"], "carte bancaire") == 0.0

    def test_partial_match_returns_fraction(self) -> None:
        result = score_fact_provenance_coverage(["virement", "carte"], "virement")
        assert result == 0.5

    def test_accent_insensitive(self) -> None:
        assert score_fact_provenance_coverage(["Sébastien"], "Sebastien Boutet") == 1.0

    def test_case_insensitive(self) -> None:
        assert score_fact_provenance_coverage(["VIREMENT"], "virement") == 1.0

    def test_or_alternatives(self) -> None:
        assert score_fact_provenance_coverage(["virement|carte"], "carte bleue") == 1.0

    def test_or_alternatives_first_matches(self) -> None:
        assert score_fact_provenance_coverage(["virement|carte"], "virement entrant") == 1.0

    def test_multiple_entries_all_required(self) -> None:
        result = score_fact_provenance_coverage(
            ["virement", "carte", "2026"],
            "virement et carte en 2026",
        )
        assert result == 1.0

    def test_multiple_entries_partial(self) -> None:
        result = score_fact_provenance_coverage(
            ["virement", "carte", "2026"],
            "virement seulement",
        )
        assert abs(result - 1 / 3) < 1e-9


class TestEvalCaseExpectedProvenance:
    def test_expected_provenance_defaults_to_empty(self) -> None:
        case = EvalCase(id="x", question="Q?")
        assert case.expected_provenance == []

    def test_expected_provenance_set(self) -> None:
        case = EvalCase(
            id="x",
            question="Q?",
            expected_provenance=["virement", "relevé"],
        )
        assert case.expected_provenance == ["virement", "relevé"]

    def test_backward_compat_existing_case_fields_unchanged(self) -> None:
        case = EvalCase(
            id="old",
            question="Old question?",
            expected_documents=["doc1"],
            expected_entities=["entity1"],
            expected_facts=["fact1"],
        )
        assert case.expected_provenance == []


class TestEvalCaseResultProvenanceCoverage:
    def _make_result(self, fpc: float = 1.0) -> EvalCaseResult:
        return EvalCaseResult(
            case_id="test",
            question="Q?",
            mode="hybrid",
            answer="answer text",
            document_ids=[],
            doc_coverage=1.0,
            entity_coverage=1.0,
            fact_coverage=1.0,
            fact_provenance_coverage=fpc,
            forbidden_violations=0,
            passed=True,
        )

    def test_field_exists(self) -> None:
        r = self._make_result(fpc=0.75)
        assert r.fact_provenance_coverage == 0.75

    def test_default_is_1_for_old_cases(self) -> None:
        # Existing cases have no expected_provenance → fpc should be 1.0.
        r = self._make_result(fpc=1.0)
        assert r.fact_provenance_coverage == 1.0

    def test_passed_false_when_fpc_below_1(self) -> None:
        r = self._make_result(fpc=0.5)
        r = r.model_copy(update={"passed": r.doc_coverage == 1.0 and r.fact_provenance_coverage == 1.0})
        assert r.passed is False

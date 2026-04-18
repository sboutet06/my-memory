"""Unit tests for eval scoring — pure substring/set operations, no LLM."""
from __future__ import annotations

from evaluation.scorer import (
    count_forbidden,
    score_document_coverage,
    score_entity_coverage,
    score_fact_coverage,
)


# -- document coverage -----------------------------------------------------

def test_doc_coverage_prefix_match() -> None:
    expected = ["5905ca2e", "131e8b71"]
    actual = [
        "5905ca2e-02d2-4063-b9e0-b3bcdf17ede9",
        "131e8b71-ab26-46eb-8988-1abb02ceada3",
        "07818304-dffb-4b90-902c-d3c042816d68",
    ]
    assert score_document_coverage(expected, actual) == 1.0


def test_doc_coverage_partial() -> None:
    expected = ["a", "b"]
    actual = ["aaaa", "cccc"]
    assert score_document_coverage(expected, actual) == 0.5


def test_doc_coverage_empty_expected_is_perfect() -> None:
    assert score_document_coverage([], ["whatever"]) == 1.0


def test_doc_coverage_empty_actual_is_zero_when_expected_nonempty() -> None:
    assert score_document_coverage(["x"], []) == 0.0


def test_doc_coverage_nfc_matches_nfd_filenames() -> None:
    """macOS filesystems return NFD, cases.json is authored in NFC."""
    nfc_prefix = "Déclaration Impôts"              # NFC: é is U+00E9
    nfd_filename = "De\u0301claration Impo\u0302ts 2010.pdf"  # NFD
    assert score_document_coverage([nfc_prefix], [nfd_filename]) == 1.0


# -- entity / fact coverage (substring, case-insensitive) -----------------

def test_entity_coverage_case_insensitive() -> None:
    expected = ["Sébastien Boutet", "MAAF"]
    answer = "Le client sébastien BOUTET a souscrit chez maaf."
    assert score_entity_coverage(expected, answer) == 1.0


def test_entity_coverage_partial() -> None:
    expected = ["Alice", "Bob", "Carol"]
    answer = "Alice and Bob went for a walk."
    assert score_entity_coverage(expected, answer) == 2 / 3


def test_fact_coverage_substring_match() -> None:
    expected = ["3370€", "15 février 2013"]
    answer = "Avis d'imposition de 3370€ émis, échéance 15 février 2013."
    assert score_fact_coverage(expected, answer) == 1.0


def test_empty_expected_lists_score_perfect() -> None:
    assert score_entity_coverage([], "anything") == 1.0
    assert score_fact_coverage([], "anything") == 1.0


# -- forbidden terms -------------------------------------------------------

def test_forbidden_none_present() -> None:
    assert count_forbidden(["wrong_address"], "Clean answer.") == 0


def test_forbidden_case_insensitive() -> None:
    assert count_forbidden(["Mougins"], "Lives in MOUGINS.") == 1


def test_forbidden_counts_each_term_once_regardless_of_repeats() -> None:
    """Score is term-level, not occurrence-level: 1 forbidden term = 1 violation."""
    assert count_forbidden(["mougins"], "mougins mougins mougins") == 1


def test_forbidden_multiple_terms() -> None:
    answer = "Ref: Alice and Bob."
    assert count_forbidden(["Alice", "Charlie"], answer) == 1


def test_empty_forbidden_list_zero_violations() -> None:
    assert count_forbidden([], "anything") == 0

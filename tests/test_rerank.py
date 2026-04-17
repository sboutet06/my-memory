"""Tests for the rerank result-shape contract."""
from __future__ import annotations

from extraction.rerank import _format_results


def test_format_results_returns_index_based_dicts() -> None:
    scores = [0.1, 0.9, 0.5]
    out = _format_results(scores)
    assert isinstance(out, list)
    assert all("index" in r and "relevance_score" in r for r in out)


def test_format_results_sorted_descending_by_score() -> None:
    scores = [0.1, 0.9, 0.5]
    out = _format_results(scores)
    assert [r["index"] for r in out] == [1, 2, 0]
    assert out[0]["relevance_score"] == 0.9


def test_format_results_top_n_truncates() -> None:
    scores = [0.1, 0.2, 0.3, 0.4]
    out = _format_results(scores, top_n=2)
    assert len(out) == 2
    assert [r["index"] for r in out] == [3, 2]


def test_format_results_empty_input() -> None:
    assert _format_results([]) == []


def test_format_results_top_n_none_returns_all() -> None:
    scores = [0.1, 0.2, 0.3]
    out = _format_results(scores, top_n=None)
    assert len(out) == 3

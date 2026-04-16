"""CLI-level tests for `python -m extraction` argument parsing.

Live LLM/rag calls are not exercised — those live under integration.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from extraction.__main__ import build_parser


def test_extract_is_a_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["extract"])
    assert args.cmd == "extract"
    assert args.store == Path("store")


def test_extract_accepts_store_and_working_dir() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["extract", "--store", "/tmp/s", "--working-dir", "/tmp/w"]
    )
    assert args.store == Path("/tmp/s")
    assert args.working_dir == Path("/tmp/w")


def test_query_requires_question() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["query"])


def test_query_accepts_question_and_mode() -> None:
    parser = build_parser()
    args = parser.parse_args(["query", "Who is Alice?", "--mode", "local"])
    assert args.cmd == "query"
    assert args.question == "Who is Alice?"
    assert args.mode == "local"


def test_query_default_mode_is_hybrid() -> None:
    parser = build_parser()
    args = parser.parse_args(["query", "Anything"])
    assert args.mode == "hybrid"


def test_query_rejects_unknown_mode() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["query", "Q", "--mode", "unknown"])


def test_query_supports_json_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["query", "Q", "--json"])
    assert args.json is True


def test_no_subcommand_errors() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])

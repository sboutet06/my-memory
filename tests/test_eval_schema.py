"""Validation tests for the eval case schema + cases file."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation.schema import EvalCase, load_cases

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_FILE = REPO_ROOT / "evaluation" / "cases.json"


def test_case_requires_id_and_question() -> None:
    with pytest.raises(ValidationError):
        EvalCase(id="", question="")


def test_case_defaults() -> None:
    c = EvalCase(id="x", question="hello")
    assert c.mode == "hybrid"
    assert c.expected_documents == []
    assert c.expected_entities == []
    assert c.expected_facts == []
    assert c.forbidden_facts == []
    assert c.tags == []


def test_case_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        EvalCase(id="x", question="q", mode="banana")


def test_cases_file_is_loadable() -> None:
    """The bundled cases.json must parse cleanly."""
    assert CASES_FILE.is_file(), f"missing {CASES_FILE}"
    cases = load_cases(CASES_FILE)
    assert len(cases) >= 3
    # Every case has a unique id.
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))


def test_cases_file_has_seed_dogfood_cases() -> None:
    """The first seed cases come from real dogfooding — keep them tagged."""
    cases = load_cases(CASES_FILE)
    tags = {tag for c in cases for tag in c.tags}
    # These categories came up in actual conversation:
    assert "temporal" in tags
    assert "aggregation" in tags or "table" in tags


def test_load_cases_from_explicit_dict(tmp_path: Path) -> None:
    payload = {
        "cases": [
            {
                "id": "smoke-1",
                "question": "smoke",
                "tags": ["smoke"],
            }
        ]
    }
    p = tmp_path / "c.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    cases = load_cases(p)
    assert len(cases) == 1
    assert cases[0].id == "smoke-1"

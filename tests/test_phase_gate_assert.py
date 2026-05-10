"""Tests for scripts/phase_gate_assert.py — Phase 8b.7.

The asserter reads the eval --json payload and verifies per-bucket
means against the v0.5 thresholds. These tests exercise the bucket
classifier + threshold logic without needing live eval data.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "phase_gate_assert.py"


def _run_with(payload: dict, tmp_path: Path) -> tuple[int, str, str]:
    payload_file = tmp_path / "eval.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(payload_file)],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout, result.stderr


def _baseline_pass_result(case_id: str = "baseline-1") -> dict:
    """Result that satisfies the baseline floors."""
    return {
        "case_id": case_id, "question": "q", "mode": "hybrid",
        "answer": "a", "document_ids": [],
        "doc_coverage": 1.0, "entity_coverage": 1.0, "fact_coverage": 1.0,
        "fact_provenance_coverage": 1.0, "conflict_detection_coverage": 1.0,
        "temporal_accuracy": 1.0, "abstention_accuracy": 1.0,
        "forbidden_violations": 0, "passed": True,
    }


def test_all_buckets_at_ceiling_passes(tmp_path: Path) -> None:
    payload = {
        "results": [
            _baseline_pass_result(),
            {**_baseline_pass_result("fl-1"), "fact_provenance_coverage": 0.9},
            {**_baseline_pass_result("adv-1"), "conflict_detection_coverage": 0.95},
            {**_baseline_pass_result("p8-1"), "temporal_accuracy": 0.95},
            {**_baseline_pass_result("p8b6-1"), "abstention_accuracy": 1.0},
        ],
    }
    # Need cases.json on disk so the asserter can read tags. We can't
    # mutate the real one — make sure the test cases at least exist with
    # the right tags by referencing the actual eval/cases.json.
    # Use case_ids from the real cases.json so the bucket classifier
    # finds the expected tag set.
    payload["results"][0]["case_id"] = "doc-list-people"   # untagged → baseline
    payload["results"][1]["case_id"] = "fact-evidence-bank-tx"  # fact-level
    payload["results"][2]["case_id"] = "adversarial-address-conflict"  # adversarial
    payload["results"][3]["case_id"] = "temporal-address-2017"  # phase8
    payload["results"][4]["case_id"] = "abstention-no-medical-history"  # phase8b6

    code, out, err = _run_with(payload, tmp_path)
    assert code == 0, f"stdout={out} stderr={err}"
    assert "OK" in out
    assert "FAIL" not in out


def test_below_threshold_fails(tmp_path: Path) -> None:
    payload = {
        "results": [
            {**_baseline_pass_result("fact-evidence-bank-tx"),
             "fact_provenance_coverage": 0.50},  # below 0.80
        ],
    }
    code, out, err = _run_with(payload, tmp_path)
    assert code == 1
    assert "FAIL" in out or "FAIL" in err


def test_baseline_regression_fails(tmp_path: Path) -> None:
    payload = {
        "results": [
            {**_baseline_pass_result("doc-list-people"), "doc_coverage": 0.50},
        ],
    }
    code, out, err = _run_with(payload, tmp_path)
    assert code == 1
    assert "baseline" in out or "baseline" in err


def test_aggregated_runs_shape_supported(tmp_path: Path) -> None:
    """`--runs N --json` shape with raw_runs[] also works."""
    case = _baseline_pass_result("doc-list-people")
    payload = {
        "runs": 3,
        "aggregates": [],
        "raw_runs": [[case], [case], [case]],
    }
    code, out, err = _run_with(payload, tmp_path)
    assert code == 0, f"stdout={out} stderr={err}"


def test_missing_payload_fields_raises(tmp_path: Path) -> None:
    code, _, _ = _run_with({"unrelated": "shape"}, tmp_path)
    assert code != 0


def test_skip_buckets_with_no_cases(tmp_path: Path) -> None:
    """If only baseline cases run, phase-bucket lines say SKIP, not FAIL."""
    payload = {"results": [_baseline_pass_result("doc-list-people")]}
    code, out, err = _run_with(payload, tmp_path)
    assert code == 0
    assert "SKIP" in out

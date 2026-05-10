#!/usr/bin/env python3
"""Phase 8b.7 — assert v0.5 phase-gate metric thresholds.

Reads JSON output from `python -m evaluation --runs N --json` and
asserts the per-bucket means defined in tasks.md §Phase 8b.7. Exits
non-zero if ANY threshold is violated.

Buckets (driven by case `tags` in evaluation/cases.json):

    fact-level   → fact_provenance_coverage     ≥ 0.80
    adversarial  → conflict_detection_coverage  ≥ 0.90
    phase8       → temporal_accuracy            ≥ 0.90
    phase8b6     → abstention_accuracy          ≥ 0.75
    healthcare   → ≥ 5 / 25 cases yielding ≥ 1 Fact (8b.5b)
    baseline     → doc_coverage ≥ 0.92, entity_coverage ≥ 0.98,
                   fact_coverage ≥ 1.00 (no regression from tasks.md §1)

`baseline` = cases NOT tagged with any of the above bucket tags.

Usage:
    python scripts/phase_gate_assert.py <eval-output.json>

The eval-output.json must be the full --json payload (single-run shape
or `--runs N` aggregated shape).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean


BUCKET_TAGS = ("fact-level", "adversarial", "phase8", "phase8b6")

# (metric_attr_on_case_result, threshold)
PASS_RULES: dict[str, tuple[str, float]] = {
    "fact-level": ("fact_provenance_coverage", 0.80),
    "adversarial": ("conflict_detection_coverage", 0.90),
    "phase8": ("temporal_accuracy", 0.90),
    "phase8b6": ("abstention_accuracy", 0.75),
}

BASELINE_FLOORS: dict[str, float] = {
    "doc_coverage": 0.92,
    "entity_coverage": 0.98,
    "fact_coverage": 1.00,
}


def _load_case_tags() -> dict[str, list[str]]:
    """Read cases.json once to look up per-case tags."""
    cases_path = Path(__file__).resolve().parent.parent / "evaluation" / "cases.json"
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    return {c["id"]: c.get("tags") or [] for c in data.get("cases", [])}


def _flatten_results(payload: dict) -> list[dict]:
    """Return one result dict per case-run.

    Handles both --runs=1 shape (`{"summary": ..., "results": [...]}`)
    and `--runs N` shape (`{"aggregates": [...], "raw_runs": [[...], [...]]}`).
    """
    if "results" in payload:
        return payload["results"]
    if "raw_runs" in payload:
        flat: list[dict] = []
        for run in payload["raw_runs"]:
            flat.extend(run)
        return flat
    raise SystemExit("eval JSON missing both 'results' and 'raw_runs' keys")


def _bucket(case_id: str, tags: list[str]) -> str:
    for bucket in BUCKET_TAGS:
        if bucket in tags:
            return bucket
    return "baseline"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: phase_gate_assert.py <eval-json>", file=sys.stderr)
        return 2

    payload = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    case_tags = _load_case_tags()
    results = _flatten_results(payload)
    if not results:
        print("no eval results in payload", file=sys.stderr)
        return 2

    # Group results by bucket.
    by_bucket: dict[str, list[dict]] = {}
    for r in results:
        cid = r["case_id"]
        bucket = _bucket(cid, case_tags.get(cid, []))
        by_bucket.setdefault(bucket, []).append(r)

    failed: list[str] = []
    print("=== phase-gate v0.5 ===")
    for bucket, (attr, floor) in PASS_RULES.items():
        rs = by_bucket.get(bucket, [])
        if not rs:
            print(f"  {bucket:14s}: SKIP (no cases tagged)")
            continue
        m = mean(r.get(attr, 0.0) for r in rs)
        status = "OK" if m >= floor else "FAIL"
        print(f"  {bucket:14s}: {attr}={m:.3f} (≥ {floor}) → {status}")
        if m < floor:
            failed.append(f"{bucket}: {attr}={m:.3f} < {floor}")

    rs = by_bucket.get("baseline", [])
    if rs:
        for attr, floor in BASELINE_FLOORS.items():
            m = mean(r.get(attr, 0.0) for r in rs)
            status = "OK" if m >= floor else "FAIL"
            print(f"  baseline      : {attr}={m:.3f} (≥ {floor}) → {status}")
            if m < floor:
                failed.append(f"baseline: {attr}={m:.3f} < {floor}")
    else:
        print("  baseline      : SKIP (no untagged cases)")

    if failed:
        print("\nFAILED:", file=sys.stderr)
        for f in failed:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("\nphase-gate v0.5 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env bash
# Phase 8b.7 — v0.5 end-to-end phase gate.
#
# Runs the full extraction → facts → eval pipeline on the current
# repo state and asserts the per-bucket metric thresholds defined in
# tasks.md §Phase 8b.7 / charter §3.8c via scripts/phase_gate_assert.py.
#
# This is NOT idempotent at the cost level — it WILL call the LLM.
# - extract (LightRAG entity/relation): ~$0.05-0.20 against the full
#   corpus (74 docs as of 2026-05-10). Fingerprint cache (8b.3) saves
#   nothing on first run; subsequent runs are free.
# - extract-predicates: ~$0.10-0.30 (5 predicates × LLM call per doc
#   matched by trigger). Cached too.
# - eval --runs 3: ~$0.30-0.50 per pass.
#
# Total first run: ~$1-2. Subsequent runs (cache warm): ~$0.30 (eval
# alone, cache cleared between runs by --runs).
#
# Exit 0 → all thresholds met. Non-zero → at least one regression.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

source venv/bin/activate

eval_output="$(mktemp -t phase-gate-eval-XXXXXX.json)"
trap 'rm -f "$eval_output"' EXIT

echo "[1/12] Ingest synthetic + OCR + medical corpora (idempotent)"
python -m ingestion raw-synthetic/ 2>&1 | tail -3 || true
python -m ingestion raw-ocr/ 2>&1 | tail -3 || true
python -m ingestion raw-medical/ 2>&1 | tail -3 || true

echo
echo "[2/12] Extract entities / relations (LightRAG)"
python -m extraction extract

echo
echo "[3/12] Extract structured pack records (bank Transaction → Fact)"
python -m extraction extract-structured

echo
echo "[4/12] Extract predicate Facts (address/birthdate/employer/diagnosis/medication)"
python -m extraction extract-predicates

echo
echo "[5/12] Annotate temporal [sourced: …] prefixes on nodes/edges"
python -m extraction annotate-temporal

echo
echo "[6/12] Refresh per-doc summary chunks (chunks_vdb)"
python -m extraction enhance-retrieval

# Profile/Catalog thresholds tuned for the 74-doc v0.5 corpus.
# Defaults (2/2) explode to ~760 nodes and crowd retrieval slots; 3/4
# yields ~150 nodes (close to the 87-node Phase 5.7 baseline) and
# preserves the original baseline doc_coverage. See docs/intent.md
# 2026-05-10 phase-gate calibration.
echo
echo "[7/12] Build Profile/Catalog index nodes (min_docs=3, min_entities=4)"
python -m extraction build-indexes --min-docs-for-profile 3 --min-entities-for-catalog 4

echo
echo "[8/12] Detect conflicts"
python -m facts detect-conflicts

echo
echo "[9/12] Apply replaced_by chains"
python -m facts apply-replacements

echo
echo "[10/12] Supersede time_varying facts"
python -m facts supersede

echo
echo "[11/12] Eval × 3 runs (cache cleared between runs)"
python -m evaluation --runs 3 --json > "$eval_output"

echo
echo "[12/12] Assert thresholds"
python scripts/phase_gate_assert.py "$eval_output"

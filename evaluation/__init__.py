"""Phase 0: evaluation harness.

Measures answer quality and run-to-run consistency of the extraction
query layer against a versioned set of gold-standard Q/A cases. Scoring
is pure substring/set operations — no LLM-as-judge (adds cost and
noise). Meant to be the floor under every future retrieval/graph
change: if a refactor moves scores down, we see it.
"""
from evaluation.schema import EvalCase, EvalCaseResult, load_cases

__all__ = ["EvalCase", "EvalCaseResult", "load_cases"]

"""facts — fact-level provenance layer (Phase 6).

Provides Fact, Claim, Conflict, Predicate schemas and a JSONL-backed
FactStore. Lives as an overlay on top of the LightRAG extraction store;
entities and relations stay in LightRAG, facts reference them by ID.
"""
from facts.detector import detect_all_conflicts, detect_conflict_for_fact
from facts.models import Claim, Conflict, Fact, FactResult, Predicate
from facts.predicates import PredicateRegistry
from facts.store import DuplicateIDError, FactStore

__all__ = [
    "Claim",
    "Conflict",
    "DuplicateIDError",
    "Fact",
    "FactResult",
    "FactStore",
    "Predicate",
    "PredicateRegistry",
    "detect_all_conflicts",
    "detect_conflict_for_fact",
]

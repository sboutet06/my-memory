"""Conflict detector — Phase 7.

Two facts with the same (subject_id, predicate) and different canonical_values
produce a Conflict unless the predicate is declared allow_multi=True.

Unknown predicates default to time_varying=False, allow_multi=False, which
means any value disagreement produces a Conflict (D2: safer than silent merge).

Two entry points:
- detect_conflict_for_fact(): called per-fact after append; returns Conflict or None.
- detect_all_conflicts():     batch scan of the full store; replaces conflicts.jsonl.
"""
from __future__ import annotations

import logging
from itertools import combinations

from facts.models import Conflict, Fact
from facts.predicates import PredicateRegistry
from facts.store import FactStore

logger = logging.getLogger(__name__)


def detect_conflict_for_fact(
    store: FactStore,
    fact: Fact,
    registry: PredicateRegistry,
) -> Conflict | None:
    """Check if *fact* conflicts with any existing fact in the store.

    Returns the Conflict if one was created/updated, None if no conflict.
    Writes the Conflict to the store if it does not exist; uses
    replace_conflicts when updating an existing one.
    """
    pred = registry.get(fact.predicate)
    if pred.allow_multi:
        return None

    peers = store.facts_for_subject_predicate(fact.subject_id, fact.predicate)
    conflicting = [p for p in peers if p.id != fact.id and p.canonical_value != fact.canonical_value]
    if not conflicting:
        return None

    all_ids = sorted({fact.id} | {p.id for p in conflicting})
    conflict_id = Conflict(subject_id=fact.subject_id, predicate=fact.predicate).id

    existing = store.get_conflict(conflict_id)
    if existing is not None:
        merged_ids = sorted(set(existing.competing_fact_ids) | set(all_ids))
        updated = Conflict(
            subject_id=existing.subject_id,
            predicate=existing.predicate,
            competing_fact_ids=merged_ids,
            status=existing.status,
            resolution=existing.resolution,
        )
        all_conflicts = [c if c.id != conflict_id else updated for c in store.all_conflicts()]
        store.replace_conflicts(all_conflicts)
        return updated

    conflict = Conflict(
        subject_id=fact.subject_id,
        predicate=fact.predicate,
        competing_fact_ids=all_ids,
        status="open",
    )
    store.append_conflict(conflict)
    return conflict


def detect_all_conflicts(
    store: FactStore,
    registry: PredicateRegistry,
) -> list[Conflict]:
    """Batch scan: find all conflicts in the store and replace conflicts.jsonl.

    Idempotent — running twice on the same store produces the same result.
    Preserves resolved status/resolution on re-runs if the conflict ID matches.
    """
    existing_by_id = {c.id: c for c in store.all_conflicts()}

    # Group facts by (subject_id, predicate)
    groups: dict[tuple[str, str], list[Fact]] = {}
    for fact in store.all_facts():
        key = (fact.subject_id, fact.predicate)
        groups.setdefault(key, []).append(fact)

    new_conflicts: list[Conflict] = []
    for (subject_id, predicate), facts in groups.items():
        pred = registry.get(predicate)
        if pred.allow_multi:
            continue

        unique_values = {f.canonical_value for f in facts}
        if len(unique_values) <= 1:
            continue

        all_ids = sorted(f.id for f in facts)
        template = Conflict(subject_id=subject_id, predicate=predicate)
        conflict_id = template.id

        if conflict_id in existing_by_id:
            old = existing_by_id[conflict_id]
            merged_ids = sorted(set(old.competing_fact_ids) | set(all_ids))
            new_conflicts.append(Conflict(
                subject_id=subject_id,
                predicate=predicate,
                competing_fact_ids=merged_ids,
                status=old.status,
                resolution=old.resolution,
            ))
        else:
            new_conflicts.append(Conflict(
                subject_id=subject_id,
                predicate=predicate,
                competing_fact_ids=all_ids,
                status="open",
            ))

    store.replace_conflicts(new_conflicts)
    logger.info("detect_all_conflicts: %d conflicts found", len(new_conflicts))
    return new_conflicts

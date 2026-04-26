"""Supersession engine — Phase 8.4.

For time_varying predicates, a Fact with later valid_from supersedes the
earlier one (sets its valid_to = later.valid_from - 1 day). The earlier
fact is NOT deleted — history is preserved for as_of queries.

For time_invariant predicates: no supersession (those are conflicts).
For allow_multi predicates: no supersession (coexistence is intentional).

Idempotent: a second run finds nothing more to update.
Manual valid_to (e.g., from a correction) is preserved.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterable

from facts.models import Fact
from facts.predicates import PredicateRegistry
from facts.store import FactStore

logger = logging.getLogger(__name__)


def run_supersession(store: FactStore, registry: PredicateRegistry) -> int:
    """Apply temporal supersession to all time_varying facts in the store.

    Returns the number of facts whose valid_to was set during this run.
    Re-runs are idempotent: a fact with a non-null valid_to is left alone.
    """
    facts = list(store.all_facts())
    if not facts:
        return 0

    # Group facts by (subject_id, predicate)
    groups: dict[tuple[str, str], list[Fact]] = {}
    for fact in facts:
        groups.setdefault((fact.subject_id, fact.predicate), []).append(fact)

    by_id: dict[str, Fact] = {f.id: f for f in facts}
    changed = 0

    for (subject_id, predicate), group in groups.items():
        pred = registry.get(predicate)
        # Skip predicates where supersession does not apply.
        if not pred.time_varying or pred.allow_multi:
            continue

        # Need valid_from to reason about ordering.
        dated = sorted(
            (f for f in group if f.valid_from is not None),
            key=lambda f: f.valid_from,
        )
        if len(dated) < 2:
            continue

        for earlier, later in zip(dated, dated[1:]):
            if earlier.valid_to is not None:
                continue  # respect manual / pre-existing valid_to
            if earlier.valid_from == later.valid_from:
                continue  # same date → ambiguous, skip
            new_valid_to = later.valid_from - timedelta(days=1)
            updated = Fact(
                subject_id=earlier.subject_id,
                predicate=earlier.predicate,
                canonical_value=earlier.canonical_value,
                value=earlier.value,
                source_doc_id=earlier.source_doc_id,
                valid_from=earlier.valid_from,
                valid_to=new_valid_to,
                claim_ids=earlier.claim_ids,
                confidence=earlier.confidence,
            )
            by_id[updated.id] = updated
            changed += 1

    if changed:
        store.replace_facts(list(by_id.values()))
        logger.info("supersession: closed valid_to on %d fact(s)", changed)

    return changed

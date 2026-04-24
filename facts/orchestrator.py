"""Fact orchestration — calls inject_facts on each registered pack.

Dependency direction: facts.orchestrator → packs.registry (→ packs.*
→ facts.models). facts.models does not import packs, so no cycle.

Design: packs own the write — each pack's inject_facts receives the
FactStore and writes its own Facts/Claims, handling DuplicateIDError
for idempotent re-runs. The orchestrator aggregates return values.
"""
from __future__ import annotations

import logging

from facts.models import FactResult
from facts.store import FactStore
from packs.registry import PackRegistry

logger = logging.getLogger(__name__)


def run_inject_facts(
    pack_registry: PackRegistry,
    result: dict,
    facts_store: FactStore,
    rag=None,
) -> FactResult:
    """Iterate all registered packs and call their inject_facts hook.

    Packs without inject_facts are silently skipped (backward-compat).
    Exceptions in a pack's hook are logged and do not abort processing.
    Returns an aggregated FactResult across all packs.
    """
    combined = FactResult()

    for pack in pack_registry.list():
        hook = getattr(pack, "inject_facts", None)
        if hook is None:
            continue
        try:
            fr: FactResult = hook(rag, facts_store, result)
            combined.facts.extend(fr.facts)
            combined.claims.extend(fr.claims)
        except Exception as exc:
            logger.warning("pack %r.inject_facts() raised: %s", pack.name, exc)

    return combined

"""Read-side helpers that apply derivation-layer corrections.

Scope for Phase 3.6: lightweight lookups — collect the user's decisions
into plain data structures. Actually applying alias decisions to the
persisted graph (merge/split/veto rewrites) is Phase 3.7.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from corrections.derivation_schemas import (
    AliasAction,
    AliasCorrection,
    EntityTypeBucket,
)


# ----------------------------- entity types ------------------------------


def collect_entity_type_overrides(
    buckets: Iterable[EntityTypeBucket],
) -> dict[str, str]:
    """Flatten user `override_type` across all buckets.

    Later buckets win on conflict (caller controls iteration order).
    """
    out: dict[str, str] = {}
    for b in buckets:
        out.update(b.overrides_by_name())
    return out


def apply_entity_type_overrides(
    graph: dict[str, dict[str, Any]],
    overrides: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Return a shallow-copied graph with `entity_type` rewritten per override."""
    out: dict[str, dict[str, Any]] = {}
    for name, node in graph.items():
        new_node = dict(node)
        if name in overrides:
            new_node["entity_type"] = overrides[name]
        out[name] = new_node
    return out


# -------------------------------- aliases --------------------------------


@dataclass
class AliasDecision:
    """Flattened form of an `AliasCorrection` ready for a graph mutator."""

    cluster: str
    members: list[str]
    action: AliasAction
    canonical: Optional[str] = None
    split_groups: list[list[str]] = field(default_factory=list)


def collect_alias_decisions(
    corrections: Iterable[AliasCorrection],
) -> list[AliasDecision]:
    out: list[AliasDecision] = []
    for c in corrections:
        out.append(AliasDecision(
            cluster=c.cluster,
            members=list(c.members),
            action=c.effective_action(),
            canonical=c.overrides.get("canonical"),
            split_groups=list(c.overrides.get("split_groups") or []),
        ))
    return out

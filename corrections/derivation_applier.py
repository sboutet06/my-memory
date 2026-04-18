"""Turn user-reviewed derivation corrections into a concrete action Plan.

Pure function. Callers execute the plan against a real graph separately
(see `extraction.graph.apply_derivation_plan`).

Scope (what the plan says to do):
  - Entity-type rewrites: `node['entity_type'] = override_type`
  - Alias operations: MERGE / SPLIT turn into one or more
    `MergeOp(canonical, sources)`. ACCEPT and VETO are no-ops on the
    already-stored graph (the pipeline's inferred decision — no merge
    for ambiguous clusters — already holds).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from corrections.derivation_schemas import (
    AliasAction,
    AliasCorrection,
    EntityTypeBucket,
)
from extraction.alias import pick_canonical


@dataclass(frozen=True)
class TypeChange:
    name: str
    old_type: str
    new_type: str


@dataclass(frozen=True)
class MergeOp:
    canonical: str
    sources: tuple[str, ...]

    def __init__(self, canonical: str, sources: Iterable[str]) -> None:
        # Freeze sources as a tuple so MergeOp is hashable and easy to dedupe.
        object.__setattr__(self, "canonical", canonical)
        object.__setattr__(self, "sources", tuple(sources))


@dataclass
class Plan:
    type_changes: list[TypeChange] = field(default_factory=list)
    merge_ops: list[MergeOp] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.type_changes and not self.merge_ops

    def summary(self) -> dict:
        return {
            "type_changes": len(self.type_changes),
            "merge_ops": len(self.merge_ops),
            "warnings": len(self.warnings),
        }


# ------------------------------ planners ---------------------------------


def _plan_type_changes(
    graph: dict[str, dict],
    buckets: Iterable[EntityTypeBucket],
) -> tuple[list[TypeChange], list[str]]:
    changes: list[TypeChange] = []
    warnings: list[str] = []
    seen_names: set[str] = set()

    for bucket in buckets:
        for entry in bucket.entries:
            if not entry.override_type:
                continue
            if entry.name in seen_names:
                # Later bucket wins; drop any earlier-planned change for this name.
                changes = [c for c in changes if c.name != entry.name]
            node = graph.get(entry.name)
            if node is None:
                warnings.append(
                    f"entity-type override targets missing node {entry.name!r}"
                )
                continue
            current = node.get("entity_type") or ""
            if current == entry.override_type:
                continue
            changes.append(TypeChange(
                name=entry.name,
                old_type=current,
                new_type=entry.override_type,
            ))
            seen_names.add(entry.name)
    return changes, warnings


def _pick_canonical_for(graph: dict[str, dict], members: list[str]) -> str:
    """Same algorithm as the resolver: longest name, alphabetical tiebreak."""
    return pick_canonical(members)


def _plan_merge_op(
    graph: dict[str, dict],
    members: list[str],
    canonical_hint: str | None,
    warnings: list[str],
    cluster_id: str,
) -> MergeOp | None:
    present = [m for m in members if m in graph]
    missing = [m for m in members if m not in graph]
    if missing:
        warnings.append(
            f"cluster {cluster_id!r}: members not in graph: {missing}"
        )
    if len(present) < 2:
        return None

    if canonical_hint and canonical_hint in present:
        canonical = canonical_hint
    elif canonical_hint:
        warnings.append(
            f"cluster {cluster_id!r}: canonical {canonical_hint!r} not in graph; "
            "picking algorithmically"
        )
        canonical = _pick_canonical_for(graph, present)
    else:
        canonical = _pick_canonical_for(graph, present)

    sources = [m for m in present if m != canonical]
    if not sources:
        return None
    return MergeOp(canonical=canonical, sources=sources)


def _plan_alias_ops(
    graph: dict[str, dict],
    aliases: Iterable[AliasCorrection],
) -> tuple[list[MergeOp], list[str]]:
    ops: list[MergeOp] = []
    warnings: list[str] = []
    for c in aliases:
        action = c.effective_action()
        if action in (AliasAction.ACCEPT, AliasAction.VETO):
            continue
        if action == AliasAction.MERGE:
            op = _plan_merge_op(
                graph, list(c.members),
                canonical_hint=c.overrides.get("canonical"),
                warnings=warnings, cluster_id=c.cluster,
            )
            if op is not None:
                ops.append(op)
            continue
        if action == AliasAction.SPLIT:
            groups = c.overrides.get("split_groups") or []
            if not groups:
                warnings.append(
                    f"cluster {c.cluster!r}: action=split but split_groups empty; skipping"
                )
                continue
            for group in groups:
                op = _plan_merge_op(
                    graph, list(group),
                    canonical_hint=None,
                    warnings=warnings, cluster_id=c.cluster,
                )
                if op is not None:
                    ops.append(op)
    return ops, warnings


def build_plan(
    graph: dict[str, dict],
    *,
    buckets: Iterable[EntityTypeBucket],
    aliases: Iterable[AliasCorrection],
) -> Plan:
    """Compose a full derivation plan from the current graph state + corrections."""
    changes, w1 = _plan_type_changes(graph, buckets)
    ops, w2 = _plan_alias_ops(graph, aliases)
    return Plan(type_changes=changes, merge_ops=ops, warnings=w1 + w2)

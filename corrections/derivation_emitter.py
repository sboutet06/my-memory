"""Derivation-layer doubts emitter.

Two sources of structured uncertainty in the extraction pipeline:

1. Entity types — the taxonomy enforcer funnels anything outside the
   allowed vocabulary to a `concept` fallback bucket (and preserves the
   LLM's original guess as `original_entity_type`). The emitter surfaces:
     - `concept_fallback`: every node landed in the fallback bucket
     - `remapped_singletons`: subset whose original guess was a
       one-off type the LLM invented (lighting/route/…)

2. Aliases — `cluster_entities` flags nodes whose pairwise matches do
   not form a clique as ambiguous and drops them from any merge. The
   emitter turns each ambiguous group into an `AliasCorrection`.

Pure functions — no I/O, no graph access. Callers pass in snapshots.
"""
from __future__ import annotations

from typing import Iterable

from corrections.derivation_io import make_slug
from corrections.derivation_schemas import (
    AliasCorrection,
    EntityTypeBucket,
    EntityTypeEntry,
)
from corrections.schemas import (
    Confidence,
    Doubt,
    SuggestedAction,
)
from extraction.provenance import parse_document_ids


def _evidence_docs(node: dict) -> list[str]:
    """`document_ids` is stored as a SEP-joined string in the graph; parse it."""
    raw = node.get("document_ids")
    if isinstance(raw, str):
        return parse_document_ids(raw)
    if isinstance(raw, list):
        return list(raw)
    return []


def _to_entry(name: str, node: dict) -> EntityTypeEntry:
    return EntityTypeEntry(
        name=name,
        inferred_type=node.get("entity_type") or "",
        evidence_docs=_evidence_docs(node),
    )


def emit_entity_type_buckets(
    graph: dict[str, dict],
    *,
    fallback: str = "concept",
) -> list[EntityTypeBucket]:
    """Produce entity-type doubts from a post-processed graph snapshot.

    `graph` is `{node_name: node_dict}`. Empty buckets are omitted.
    """
    fallback_entries: list[EntityTypeEntry] = []
    singleton_entries: list[EntityTypeEntry] = []

    for name, node in graph.items():
        t = node.get("entity_type") or ""
        if t != fallback:
            continue
        entry = _to_entry(name, node)
        fallback_entries.append(entry)
        if node.get("original_entity_type"):
            singleton_entries.append(entry)

    # Deterministic order for reproducible diffs.
    fallback_entries.sort(key=lambda e: e.name)
    singleton_entries.sort(key=lambda e: e.name)

    buckets: list[EntityTypeBucket] = []
    if fallback_entries:
        buckets.append(EntityTypeBucket(
            bucket="concept_fallback", entries=fallback_entries,
        ))
    if singleton_entries:
        buckets.append(EntityTypeBucket(
            bucket="remapped_singletons", entries=singleton_entries,
        ))
    return buckets


def _alias_doubt(n_members: int) -> Doubt:
    return Doubt(
        field="merge_decision",
        inferred_value="split",
        confidence=Confidence.LOW,
        rationale=(
            f"{n_members} surface forms passed cosine + lexical checks but "
            "did not form a clique — at least one bridges distinct entities. "
            "Pipeline dropped the group from any automatic merge. "
            "Choose `action: merge` to force, `veto` to split entirely, or "
            "`split` with `split_groups` to partition."
        ),
        suggested_action=SuggestedAction.REVIEW,
    )


def _cluster_slug(members: Iterable[str]) -> str:
    """Slug from the shortest member (most likely canonical prefix)."""
    sorted_members = sorted(members, key=lambda s: (len(s), s))
    return make_slug(sorted_members[0]) if sorted_members else "unnamed"


def emit_alias_corrections(
    *,
    ambiguous_groups: list[list[str]],
) -> list[AliasCorrection]:
    """One correction per ambiguous cluster flagged by the alias resolver."""
    out: list[AliasCorrection] = []
    seen_slugs: dict[str, int] = {}
    for group in ambiguous_groups:
        if not group:
            continue
        base_slug = _cluster_slug(group)
        # Disambiguate duplicate slugs across different groups.
        slug = base_slug
        if base_slug in seen_slugs:
            seen_slugs[base_slug] += 1
            slug = f"{base_slug}_{seen_slugs[base_slug]}"
        else:
            seen_slugs[base_slug] = 1
        out.append(AliasCorrection(
            cluster=slug,
            members=list(group),
            doubts=[_alias_doubt(len(group))],
        ))
    return out

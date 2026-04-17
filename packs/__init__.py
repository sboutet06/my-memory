"""Pack framework — pluggable domain extensions.

Core is generic (ingestion, extraction, alias resolution, temporal
annotations, retrieval) — it has no built-in notion of `Transaction`,
`Contract`, `Residence`, etc. Domain-specific schemas and extractors
live in `packs/<name>/`, get discovered at runtime, and register
themselves with a `PackRegistry`.

A pack declares:
- A name + version.
- A `matches(metadata, content_md)` predicate deciding whether it
  applies to a given ingested document.

Future extensions (deferred until a pack actually needs them):
- `extract()` for domain-specific structured records.
- `query_tools()` exposing typed retrieval functions to an agentic
  query layer.

This module ships only the contract + registry + discovery. No actual
pack implementations yet — those come in Phase 4.
"""
from packs.protocol import Pack
from packs.registry import PackRegistry, discover_packs

__all__ = ["Pack", "PackRegistry", "discover_packs"]

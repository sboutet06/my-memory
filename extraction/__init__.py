"""Layer 3: entity/relationship extraction wrapping LightRAG.

Scope (A):
- Constrain entity-type vocabulary via `addon_params`.
- Post-process node/edge provenance: derive `document_ids` from
  `file_path` so the graph is portable (no absolute local paths leaked
  as the primary key).

Not in scope:
- Entity-name normalization / fragmentation merge (deferred to B).
- Custom storage backend (Neo4j, etc. — deferred).
"""
from extraction.config import ExtractionConfig
from extraction.provenance import (
    extract_document_ids,
    parse_document_ids,
    rewrite_node_provenance,
)

__all__ = [
    "ExtractionConfig",
    "extract_document_ids",
    "parse_document_ids",
    "rewrite_node_provenance",
]

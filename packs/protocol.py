"""Pack protocol — the minimum contract a domain pack must satisfy."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Pack(Protocol):
    """A pluggable domain extension.

    Implementations live under `packs/<name>/` and expose a module-level
    `PACK` instance (typically of the pack's own class). Discovery
    imports the submodule and picks up `PACK`.

    The contract is deliberately minimal for V0 — just identity and
    per-document applicability. Structured extraction and query-tool
    hooks are added later when a pack actually needs them.
    """

    name: str
    version: str

    # Optional, introspected with getattr at consumption sites:
    #   declared_types: list[str]
    #     Entity types the pack contributes to the extraction taxonomy.
    #     Unioned with core types; the LLM is asked to use them when
    #     applicable. Packs that don't need new types can omit this.
    #   extract_structured(metadata, content_md) -> dict | None
    #     Produce structured records (pack-specific schemas) for docs
    #     this pack knows how to parse. Returns a dict `{"kind": str, ...}`
    #     on match, None otherwise. Typically deterministic (regex /
    #     parser) — LLM-backed extractors pay an extra cost per doc.

    def matches(self, metadata: dict, content_md: str) -> bool:
        """True if this pack should handle the given ingested document.

        `metadata` is the `DocumentMetadata` dict from
        `store/{doc_id}/metadata.json`; `content_md` is the Docling
        markdown content.
        """
        ...

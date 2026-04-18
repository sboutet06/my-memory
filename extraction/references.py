"""Deterministic References block — LightRAG's authoritative ref list
rewritten as `/store/<uuid>/content.md` lines the provenance regex can
parse.

Phase 5.3b rationale (see docs/intent.md): doc_coverage regressions in
eval are dominated by LLM citation-format variance. The LLM sometimes
emits a `### References` block with `[n] /path/to/store/<uuid>/…`
(scorable), sometimes with entity names (`[n] Document d'Assurance …`,
not scorable), sometimes nothing at all. LightRAG already computes the
authoritative reference list and surfaces it via `aquery_llm().raw_data
.data.references`. We rewrite that list into a canonical block and
merge it into the answer — idempotent, LLM-agnostic, parseable.

Pure functions; the caller (CLI / eval runner) is responsible for
invoking `rag.aquery_llm` and passing `raw_data.data.references`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from extraction.provenance import extract_document_ids

# Heading on the rendered block. Matching is case-sensitive on "References"
# but indifferent to leading markdown heading depth.
_REFERENCES_HEADER_RE = re.compile(
    r"(?mi)^\s*#{1,6}\s*References\s*$",
)
# A trailing block starting at "### References" (or similar) and running
# to EOF — anything the LLM wrote after that heading is replaced.
_TRAILING_BLOCK_RE = re.compile(
    r"(?mis)\n*#{1,6}\s*References\s*\n.*\Z",
)


@dataclass(frozen=True)
class Reference:
    """A single reference LightRAG computed for a query.

    Attributes:
        reference_id: The `[n]` label LightRAG assigned.
        file_path: The original absolute path (or equivalent).
        doc_id: The parsed UUID under `/store/<uuid>/`, or None if the
                path doesn't contain a store doc_id.
    """

    reference_id: str
    file_path: str
    doc_id: str | None


def _parse_one(raw: Mapping[str, str]) -> Reference | None:
    rid = str(raw.get("reference_id") or "").strip()
    fp = str(raw.get("file_path") or "").strip()
    if not rid or not fp:
        return None
    ids = extract_document_ids(fp)
    doc_id = ids[0] if ids else None
    return Reference(reference_id=rid, file_path=fp, doc_id=doc_id)


def parse_references(raw_refs: Iterable[Mapping[str, str]] | None) -> list[Reference]:
    """Normalize LightRAG's `references` list into typed `Reference` records.

    Preserves order; skips entries missing `reference_id` or `file_path`;
    deduplicates by `(reference_id, file_path)` — LightRAG can emit
    duplicates when multiple context paths map to the same doc.
    """
    if not raw_refs:
        return []
    out: list[Reference] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_refs:
        parsed = _parse_one(raw)
        if parsed is None:
            continue
        key = (parsed.reference_id, parsed.file_path)
        if key in seen:
            continue
        seen.add(key)
        out.append(parsed)
    return out


def _render_line(ref: Reference) -> str:
    """`- [1] /store/<uuid>/content.md` for scorable refs; fall back to
    the original path when no store UUID is present.
    """
    if ref.doc_id:
        path = f"/store/{ref.doc_id}/content.md"
    else:
        path = ref.file_path
    return f"- [{ref.reference_id}] {path}"


def render_references_block(refs: Iterable[Reference]) -> str:
    """Produce a canonical `### References` markdown block.

    Empty input → empty string (caller decides whether to strip a prior
    block when no refs are available).
    """
    refs = list(refs)
    if not refs:
        return ""
    lines = ["### References", ""]
    for ref in refs:
        lines.append(_render_line(ref))
    return "\n".join(lines)


def inject_references(answer: str, refs: Iterable[Reference]) -> str:
    """Return `answer` with its References block replaced by a canonical one.

    Rules:
    - Any trailing `### References …` (or `## References …`) section is
      stripped and replaced with the rendered block.
    - Empty `refs` → answer returned with any existing References block
      removed (avoid leaving a stale, possibly wrong, LLM-authored list).
    - Idempotent: running twice yields the same output.
    - Preserves `[n]` in-text bracket refs; only the trailing section is
      rewritten.
    """
    stripped = _TRAILING_BLOCK_RE.sub("", answer).rstrip()

    block = render_references_block(refs)
    if not block:
        return stripped

    return f"{stripped}\n\n{block}"


def _expand_from_index_entities(
    entities: Iterable[Mapping], *, start_id: int,
) -> list[Reference]:
    """Phase 5.7: pull `/store/<uuid>/` doc_ids out of every Profile/Catalog
    entity's description and return them as additional references.

    LightRAG builds `data.references` purely from retrieved chunks. Profile
    and Catalog nodes (synthetic, created by `write_index_nodes`) embed
    `/store/<uuid>/content.md` paths for every member doc in their
    description — when one is retrieved, those member docs are in the
    LLM's context but not in the chunks-derived reference list.

    This function extracts those paths so the canonical References block
    names them too, letting the provenance regex score doc_coverage on the
    breadth the Profile actually conveys.
    """
    out: list[Reference] = []
    seen: set[str] = set()
    next_id = start_id
    for ent in entities or ():
        if not isinstance(ent, Mapping):
            continue
        name = str(ent.get("entity_name") or "")
        if not (name.startswith("Profile: ") or name.startswith("Catalog: ")):
            continue
        desc = str(ent.get("description") or "")
        for doc_id in extract_document_ids(desc):
            if doc_id in seen:
                continue
            seen.add(doc_id)
            out.append(Reference(
                reference_id=str(next_id),
                file_path=f"/store/{doc_id}/content.md",
                doc_id=doc_id,
            ))
            next_id += 1
    return out


def _merge_refs(primary: list[Reference], extra: list[Reference]) -> list[Reference]:
    """Append refs from `extra` that bring new doc_ids. Preserves `primary`
    order and reference_ids; skips `extra` entries whose doc_id is already
    represented in `primary`.
    """
    seen_docs: set[str] = {r.doc_id for r in primary if r.doc_id}
    out = list(primary)
    for r in extra:
        if r.doc_id and r.doc_id in seen_docs:
            continue
        if r.doc_id:
            seen_docs.add(r.doc_id)
        out.append(r)
    return out


def extract_references_from_query_result(result: Mapping) -> list[Reference]:
    """Pull LightRAG's chunks-derived `data.references` list and expand it
    with Profile/Catalog entity descriptions' `/store/<uuid>/` paths
    (Phase 5.7). Chunks-only references miss broad-coverage Profiles.
    """
    data = result.get("data") if isinstance(result, Mapping) else None
    if not isinstance(data, Mapping):
        return []
    primary = parse_references(data.get("references"))
    # Start expansion ids after the chunks' sequential ids so the indices
    # remain stable-ordered and predictable.
    start = 1 + max(
        (int(r.reference_id) for r in primary if r.reference_id.isdigit()),
        default=0,
    )
    extra = _expand_from_index_entities(data.get("entities") or [], start_id=start)
    return _merge_refs(primary, extra)

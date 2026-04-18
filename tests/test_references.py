"""Pure-function tests for Phase 5.3b References injection."""
from __future__ import annotations

from extraction.references import (
    Reference,
    extract_references_from_query_result,
    inject_references,
    parse_references,
    render_references_block,
)


V4_A = "b35e7fcd-1185-4d80-bc3e-835da38253f9"
V4_B = "4c6ac394-4c65-4f3e-8da8-ea5eaf7be7d0"


def _raw(rid: str, doc_id: str | None = None, custom: str | None = None) -> dict:
    if custom is not None:
        fp = custom
    elif doc_id is None:
        fp = ""
    else:
        fp = f"/Users/x/projects/my-memory/store/{doc_id}/content.md"
    return {"reference_id": rid, "file_path": fp}


class TestParseReferences:
    def test_extracts_doc_id_from_store_path(self) -> None:
        refs = parse_references([_raw("1", V4_A)])
        assert refs == [
            Reference(
                reference_id="1",
                file_path=f"/Users/x/projects/my-memory/store/{V4_A}/content.md",
                doc_id=V4_A,
            )
        ]

    def test_non_store_path_has_no_doc_id(self) -> None:
        refs = parse_references([_raw("1", custom="some_entity_description")])
        assert refs[0].doc_id is None
        assert refs[0].file_path == "some_entity_description"

    def test_drops_entries_without_id_or_path(self) -> None:
        refs = parse_references([
            {"reference_id": "", "file_path": "/x"},
            {"reference_id": "2", "file_path": ""},
            _raw("3", V4_A),
        ])
        assert [r.reference_id for r in refs] == ["3"]

    def test_dedupes_identical_entries(self) -> None:
        refs = parse_references([
            _raw("1", V4_A),
            _raw("1", V4_A),
            _raw("2", V4_B),
        ])
        assert [r.reference_id for r in refs] == ["1", "2"]

    def test_empty_input_returns_empty_list(self) -> None:
        assert parse_references(None) == []
        assert parse_references([]) == []


class TestRenderReferencesBlock:
    def test_renders_store_refs_in_canonical_form(self) -> None:
        refs = [
            Reference("1", f"/abs/store/{V4_A}/content.md", V4_A),
            Reference("2", f"/abs/store/{V4_B}/content.md", V4_B),
        ]
        block = render_references_block(refs)
        assert block.startswith("### References")
        assert f"- [1] /store/{V4_A}/content.md" in block
        assert f"- [2] /store/{V4_B}/content.md" in block

    def test_non_store_ref_falls_back_to_raw_path(self) -> None:
        refs = [Reference("1", "Some Entity Description", None)]
        block = render_references_block(refs)
        assert "- [1] Some Entity Description" in block

    def test_empty_refs_yield_empty_block(self) -> None:
        assert render_references_block([]) == ""


class TestInjectReferences:
    def test_appends_when_no_prior_block(self) -> None:
        answer = "A short answer with [1] inline."
        refs = [Reference("1", f"/abs/store/{V4_A}/content.md", V4_A)]
        out = inject_references(answer, refs)
        assert "A short answer with [1] inline." in out
        assert f"/store/{V4_A}/content.md" in out
        assert out.count("### References") == 1

    def test_replaces_existing_wrong_refs_block(self) -> None:
        answer = (
            "Main content [1].\n\n"
            "### References\n\n"
            "*   [1] Wrong Entity Name\n"
        )
        refs = [Reference("1", f"/abs/store/{V4_A}/content.md", V4_A)]
        out = inject_references(answer, refs)
        assert "Wrong Entity Name" not in out
        assert f"/store/{V4_A}/content.md" in out
        assert out.count("### References") == 1

    def test_is_idempotent(self) -> None:
        answer = "Body [1] [2]."
        refs = [
            Reference("1", f"/a/store/{V4_A}/content.md", V4_A),
            Reference("2", f"/a/store/{V4_B}/content.md", V4_B),
        ]
        once = inject_references(answer, refs)
        twice = inject_references(once, refs)
        assert once == twice

    def test_empty_refs_strips_existing_block_to_avoid_stale_list(self) -> None:
        answer = (
            "Body.\n\n"
            "### References\n\n"
            "* [1] something stale\n"
        )
        out = inject_references(answer, [])
        assert "### References" not in out
        assert "something stale" not in out
        assert out.rstrip().endswith("Body.")

    def test_preserves_inline_bracket_refs(self) -> None:
        answer = "Paragraph one [1]. Paragraph two [2]."
        refs = [Reference("1", f"/x/store/{V4_A}/content.md", V4_A)]
        out = inject_references(answer, refs)
        assert "[1]" in out
        assert "[2]" in out

    def test_works_with_level_2_header(self) -> None:
        answer = (
            "Body.\n\n"
            "## References\n\n"
            "*   [1] legacy path\n"
        )
        refs = [Reference("1", f"/x/store/{V4_A}/content.md", V4_A)]
        out = inject_references(answer, refs)
        assert "legacy path" not in out
        assert f"/store/{V4_A}/content.md" in out


class TestExtractReferencesFromQueryResult:
    def test_unwraps_raw_data_data_references(self) -> None:
        result = {
            "data": {
                "references": [_raw("1", V4_A), _raw("2", V4_B)],
            },
        }
        refs = extract_references_from_query_result(result)
        assert [r.doc_id for r in refs] == [V4_A, V4_B]

    def test_missing_data_returns_empty(self) -> None:
        assert extract_references_from_query_result({}) == []
        assert extract_references_from_query_result({"data": None}) == []
        assert extract_references_from_query_result({"data": {}}) == []


V4_C = "3aa2c3f8-411b-4bcf-bddd-571218002ce7"
V4_D = "eec9507c-1d09-4bfa-b8e5-8792fdf9eaf3"


class TestPhase57ProfileExpansion:
    def test_profile_description_docs_are_merged_into_refs(self) -> None:
        # Chunks-derived refs have only V4_A; a retrieved Profile entity
        # lists V4_A, V4_B, V4_C in its description. Merged result should
        # have all three.
        result = {
            "data": {
                "references": [_raw("1", V4_A)],
                "entities": [
                    {
                        "entity_name": f"Profile: Sébastien Boutet",
                        "description": (
                            f"Profile of Sébastien Boutet. Appears in 3 docs:\n"
                            f"  - /store/{V4_A}/content.md (x.pdf)\n"
                            f"  - /store/{V4_B}/content.md (y.pdf)\n"
                            f"  - /store/{V4_C}/content.md (z.pdf)\n"
                        ),
                    },
                ],
            },
        }
        refs = extract_references_from_query_result(result)
        doc_ids = [r.doc_id for r in refs]
        assert V4_A in doc_ids
        assert V4_B in doc_ids
        assert V4_C in doc_ids
        # Chunks-primary ref keeps reference_id=1; new ones follow.
        primary = next(r for r in refs if r.doc_id == V4_A)
        assert primary.reference_id == "1"

    def test_catalog_entity_is_also_expanded(self) -> None:
        result = {
            "data": {
                "references": [],
                "entities": [
                    {
                        "entity_name": "Catalog: vehicle",
                        "description": (
                            f"Catalog of vehicle.\n"
                            f"  - Zoé [/store/{V4_A}/content.md]\n"
                            f"  - KIA [/store/{V4_B}/content.md]\n"
                        ),
                    },
                ],
            },
        }
        refs = extract_references_from_query_result(result)
        assert {r.doc_id for r in refs} == {V4_A, V4_B}

    def test_non_profile_non_catalog_entity_ignored(self) -> None:
        result = {
            "data": {
                "references": [],
                "entities": [
                    {
                        "entity_name": "Some Person",
                        "description": f"Lives at /store/{V4_A}/content.md",
                    },
                ],
            },
        }
        assert extract_references_from_query_result(result) == []

    def test_does_not_duplicate_doc_in_primary(self) -> None:
        """A Profile's doc that's already in chunks_refs stays at its
        original reference_id; extras only add NEW doc_ids."""
        result = {
            "data": {
                "references": [_raw("1", V4_A), _raw("2", V4_B)],
                "entities": [
                    {
                        "entity_name": "Profile: X",
                        "description": (
                            f"Appears in /store/{V4_A}/content.md and "
                            f"/store/{V4_B}/content.md and "
                            f"/store/{V4_C}/content.md."
                        ),
                    },
                ],
            },
        }
        refs = extract_references_from_query_result(result)
        # No duplicates; V4_C appended with id starting ≥3.
        doc_ids = [r.doc_id for r in refs]
        assert doc_ids.count(V4_A) == 1
        assert doc_ids.count(V4_B) == 1
        assert V4_C in doc_ids

    def test_inject_exposes_expanded_doc_ids_for_scoring(self) -> None:
        """End-to-end: answer with expanded refs contains all doc_ids so
        `extract_document_ids` finds them."""
        result = {
            "data": {
                "references": [_raw("1", V4_A)],
                "entities": [
                    {
                        "entity_name": "Profile: Sébastien",
                        "description": f"/store/{V4_B}/content.md",
                    },
                ],
            },
        }
        refs = extract_references_from_query_result(result)
        answer = inject_references("Sébastien appears in multiple docs.", refs)
        assert f"/store/{V4_A}/content.md" in answer
        assert f"/store/{V4_B}/content.md" in answer

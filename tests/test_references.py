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

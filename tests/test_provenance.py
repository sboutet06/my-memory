"""Unit tests for provenance post-processing (file_path → document_ids)."""
from __future__ import annotations

import pytest

from extraction.provenance import (
    extract_document_ids,
    parse_document_ids,
    rewrite_node_provenance,
)

SEP = "<SEP>"  # LightRAG's internal multi-value separator.


def test_single_path_one_doc_id() -> None:
    path = "/Users/sboutet/projects/my-memory/store/5905ca2e-02d2-4063-b9e0-b3bcdf17ede9/content.md"
    assert extract_document_ids(path) == ["5905ca2e-02d2-4063-b9e0-b3bcdf17ede9"]


def test_relative_path_still_matches() -> None:
    """LightRAG stores whatever was passed — a relative CWD-rooted path must work."""
    path = "store/5905ca2e-02d2-4063-b9e0-b3bcdf17ede9/content.md"
    assert extract_document_ids(path) == ["5905ca2e-02d2-4063-b9e0-b3bcdf17ede9"]


def test_free_text_with_multiple_refs() -> None:
    """A query answer may cite several docs inline without SEP markers."""
    answer = (
        "The person appears in [1] /a/store/11111111-1111-4111-8111-111111111111/content.md "
        "and [2] /b/store/22222222-2222-4222-8222-222222222222/content.md "
        "and again [3] /c/store/11111111-1111-4111-8111-111111111111/content.md."
    )
    assert extract_document_ids(answer) == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]


def test_cross_doc_sep_concatenation() -> None:
    path = (
        "/a/b/store/11111111-1111-4111-8111-111111111111/content.md"
        + SEP
        + "/c/d/store/22222222-2222-4222-8222-222222222222/content.md"
    )
    ids = extract_document_ids(path)
    assert ids == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]


def test_deduplicates_repeated_ids() -> None:
    # Same chunk hashed twice, same doc — single id in output.
    uid = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    path = f"/x/store/{uid}/content.md{SEP}/y/store/{uid}/content.md"
    assert extract_document_ids(path) == [uid]


def test_empty_path_returns_empty_list() -> None:
    assert extract_document_ids("") == []
    assert extract_document_ids(None) == []  # type: ignore[arg-type]


def test_path_without_uuid_returns_empty() -> None:
    assert extract_document_ids("/tmp/random.md") == []


def test_preserves_order_of_first_occurrence() -> None:
    a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    path = f"/x/store/{b}/content.md{SEP}/x/store/{a}/content.md{SEP}/x/store/{b}/content.md"
    assert extract_document_ids(path) == [b, a]


def test_rewrite_node_adds_document_ids_field() -> None:
    node = {
        "entity_id": "Alice",
        "entity_type": "person",
        "file_path": "/x/store/11111111-1111-4111-8111-111111111111/content.md",
        "source_id": "chunk-abc",
    }
    rewritten = rewrite_node_provenance(dict(node))
    # Stored as SEP-joined string (GraphML needs a scalar).
    assert rewritten["document_ids"] == "11111111-1111-4111-8111-111111111111"
    assert parse_document_ids(rewritten["document_ids"]) == [
        "11111111-1111-4111-8111-111111111111"
    ]
    # Non-provenance fields untouched.
    assert rewritten["entity_id"] == "Alice"
    assert rewritten["entity_type"] == "person"


def test_rewrite_node_cross_doc_joins_with_sep() -> None:
    node = {
        "file_path": (
            "/x/store/11111111-1111-4111-8111-111111111111/content.md"
            + SEP
            + "/y/store/22222222-2222-4222-8222-222222222222/content.md"
        ),
    }
    rewritten = rewrite_node_provenance(node)
    assert isinstance(rewritten["document_ids"], str)
    assert parse_document_ids(rewritten["document_ids"]) == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]


def test_rewrite_node_is_idempotent() -> None:
    node = {
        "entity_id": "Alice",
        "file_path": "/x/store/11111111-1111-4111-8111-111111111111/content.md",
    }
    once = rewrite_node_provenance(dict(node))
    twice = rewrite_node_provenance(once)
    assert once["document_ids"] == twice["document_ids"]


def test_rewrite_node_with_no_file_path() -> None:
    """Defensive: node without file_path shouldn't crash, should yield empty string."""
    node = {"entity_id": "Alice"}
    rewritten = rewrite_node_provenance(dict(node))
    assert rewritten["document_ids"] == ""
    assert parse_document_ids(rewritten["document_ids"]) == []


def test_parse_document_ids_roundtrip() -> None:
    ids = ["a" * 36, "b" * 36]
    # Simulate what rewrite would produce.
    serialized = SEP.join(ids)
    assert parse_document_ids(serialized) == ids
    assert parse_document_ids("") == []
    assert parse_document_ids(None) == []


@pytest.mark.parametrize(
    "bad_input",
    [
        "/x/store/not-a-uuid/content.md",
        "/x/store/12345/content.md",
        "/x/store/../content.md",
    ],
)
def test_rejects_non_uuid_segments(bad_input: str) -> None:
    assert extract_document_ids(bad_input) == []

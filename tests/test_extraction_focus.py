"""Tests for Phase 5.6 doc-kind-routed extraction hints."""
from __future__ import annotations

from packs.personal_documents.focus import (
    extraction_hints,
    focus_for_tags,
)


class TestFocusForTags:
    def test_known_tag_maps_to_types(self) -> None:
        out = focus_for_tags(["work"])
        assert "employer" in out
        assert "role" in out
        assert "skill" in out

    def test_unknown_tag_contributes_nothing(self) -> None:
        assert focus_for_tags(["__unknown__"]) == []

    def test_other_tag_returns_empty(self) -> None:
        # `other` is deliberately unmapped — avoid biasing unclassified docs.
        assert focus_for_tags(["other"]) == []

    def test_multi_tag_union_preserves_first_seen_order(self) -> None:
        out = focus_for_tags(["work", "identity"])
        # `person` appears in both; first-seen (work) order is preserved.
        assert "person" in out
        # Both tag sets' distinctive types surface.
        assert "role" in out
        assert "identifier" in out

    def test_empty_input_returns_empty(self) -> None:
        assert focus_for_tags([]) == []
        assert focus_for_tags(None) == []  # type: ignore[arg-type]

    def test_cap_keeps_prompt_bounded(self) -> None:
        # Pile many tags; list must not grow unbounded.
        out = focus_for_tags([
            "work", "healthcare", "finance", "property",
            "vehicle", "identity", "family", "legal",
        ])
        assert len(out) <= 10


class TestExtractionHints:
    def test_reads_doc_context_from_metadata(self) -> None:
        meta = {"doc_context": ["healthcare"]}
        hints = extraction_hints(meta)
        assert "medication" in hints
        assert "diagnosis" in hints

    def test_missing_doc_context_returns_empty(self) -> None:
        assert extraction_hints({}) == []

    def test_empty_doc_context_returns_empty(self) -> None:
        assert extraction_hints({"doc_context": []}) == []


class TestPackHook:
    def test_pack_exposes_extraction_hints(self) -> None:
        from pathlib import Path
        from packs.registry import discover_packs

        pack = discover_packs(Path("packs")).get("personal_documents")
        assert callable(getattr(pack, "extraction_hints", None))
        out = pack.extraction_hints({"doc_context": ["work"]})
        assert "employer" in out
        assert "role" in out


class TestGraphPrefix:
    def test_prepend_extraction_focus_injects_line(self) -> None:
        from extraction.graph import _prepend_extraction_focus

        body = "Bulletin de paie 2015\n\nSalaire: 3000 EUR"
        out = _prepend_extraction_focus(body, ["employer", "role"])
        assert out.startswith("[EXTRACTION FOCUS:")
        assert "employer" in out
        assert "role" in out
        assert body in out

    def test_prepend_extraction_focus_no_op_on_empty(self) -> None:
        from extraction.graph import _prepend_extraction_focus

        body = "anything"
        assert _prepend_extraction_focus(body, []) == body


class TestResolveHintsAcrossPacks:
    def test_resolve_unions_hints_from_multiple_packs(self) -> None:
        from extraction.graph import _resolve_extraction_hints

        class _P:
            name = "p"

            def __init__(self, hints: list[str]) -> None:
                self._hints = hints

            def extraction_hints(self, metadata: dict) -> list[str]:
                return list(self._hints)

        packs = [_P(["a", "b"]), _P(["b", "c"])]
        out = _resolve_extraction_hints(packs, {"doc_context": ["whatever"]})
        assert out == ["a", "b", "c"]

    def test_resolve_skips_packs_without_hook(self) -> None:
        from extraction.graph import _resolve_extraction_hints

        class _NoHook:
            name = "n"

        class _WithHook:
            name = "w"

            def extraction_hints(self, meta: dict) -> list[str]:
                return ["x"]

        assert _resolve_extraction_hints([_NoHook(), _WithHook()], {}) == ["x"]

    def test_resolve_empty_when_no_packs(self) -> None:
        from extraction.graph import _resolve_extraction_hints

        assert _resolve_extraction_hints([], {}) == []

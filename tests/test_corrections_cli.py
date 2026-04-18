"""python -m corrections {review,show,stats} — multi-layer CLI."""
from __future__ import annotations

from pathlib import Path

from corrections.__main__ import main
from corrections.derivation_io import save_alias_correction, save_entity_type_bucket
from corrections.derivation_schemas import (
    AliasCorrection,
    EntityTypeBucket,
    EntityTypeEntry,
)
from corrections.io import save_source_correction
from corrections.schemas import (
    Confidence,
    CorrectionStatus,
    Doubt,
    SourceCorrection,
    SuggestedAction,
)


def _corr(doc_id: str, status: CorrectionStatus, n_doubts: int = 1) -> SourceCorrection:
    return SourceCorrection(
        document_id=doc_id,
        original_filename=f"{doc_id}.pdf",
        status=status,
        doubts=[
            Doubt(
                field="document_date", inferred_value=None,
                confidence=Confidence.LOW, rationale="r",
                suggested_action=SuggestedAction.PROVIDE,
            )
            for _ in range(n_doubts)
        ],
    )


class TestReviewCLI:
    def test_empty_root_prints_empty(self, tmp_path: Path, capsys) -> None:
        rc = main(["review", "--root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No pending" in out

    def test_lists_pending_only(self, tmp_path: Path, capsys) -> None:
        save_source_correction(tmp_path, _corr("a", CorrectionStatus.PENDING))
        save_source_correction(tmp_path, _corr("b", CorrectionStatus.REVIEWED))
        save_source_correction(tmp_path, _corr("c", CorrectionStatus.PENDING, n_doubts=2))

        rc = main(["review", "--root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "a.pdf" in out
        assert "c.pdf" in out
        assert "b.pdf" not in out  # reviewed, hidden

    def test_all_flag_lists_reviewed_too(self, tmp_path: Path, capsys) -> None:
        save_source_correction(tmp_path, _corr("a", CorrectionStatus.PENDING))
        save_source_correction(tmp_path, _corr("b", CorrectionStatus.REVIEWED))
        rc = main(["review", "--root", str(tmp_path), "--all"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "a.pdf" in out and "b.pdf" in out


class TestReviewMultiLayer:
    def test_summary_lists_all_layers(self, tmp_path: Path, capsys) -> None:
        save_source_correction(tmp_path, _corr("doc-1", CorrectionStatus.PENDING))
        save_entity_type_bucket(tmp_path, EntityTypeBucket(
            bucket="concept_fallback",
            entries=[EntityTypeEntry(name="Gabriel", inferred_type="concept")],
        ))
        save_alias_correction(tmp_path, AliasCorrection(
            cluster="sebastien_boutet",
            members=["Sébastien Boutet", "SEBASTIEN BOUTET"],
            doubts=[_corr("x", CorrectionStatus.PENDING).doubts[0]],
        ))
        rc = main(["review", "--root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "source" in out and "entity types" in out and "aliases" in out
        assert "doc-1" in out
        assert "concept_fallback" in out
        assert "sebastien_boutet" in out
        assert "Total: 3" in out

    def test_layer_filter_entity_types(self, tmp_path: Path, capsys) -> None:
        save_source_correction(tmp_path, _corr("doc-1", CorrectionStatus.PENDING))
        save_entity_type_bucket(tmp_path, EntityTypeBucket(
            bucket="concept_fallback",
            entries=[EntityTypeEntry(name="X", inferred_type="concept")],
        ))
        rc = main(["review", "entity-types", "--root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "concept_fallback" in out
        assert "doc-1" not in out


class TestShow:
    def test_show_source(self, tmp_path: Path, capsys) -> None:
        save_source_correction(tmp_path, _corr("doc-1", CorrectionStatus.PENDING))
        rc = main(["show", "doc-1", "--root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "document_id: doc-1" in out
        # inline hint survives print
        assert "pending | reviewed" in out

    def test_show_entity_types(self, tmp_path: Path, capsys) -> None:
        save_entity_type_bucket(tmp_path, EntityTypeBucket(
            bucket="concept_fallback",
            entries=[EntityTypeEntry(name="Gabriel", inferred_type="concept")],
        ))
        rc = main(["show", "concept_fallback", "--root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "bucket: concept_fallback" in out
        assert "person" in out and "organization" in out  # hint

    def test_show_missing_returns_1(self, tmp_path: Path) -> None:
        rc = main(["show", "nope", "--root", str(tmp_path)])
        assert rc == 1


class TestStats:
    def test_stats_counts_across_layers(self, tmp_path: Path, capsys) -> None:
        save_source_correction(tmp_path, _corr("a", CorrectionStatus.PENDING))
        save_source_correction(tmp_path, _corr("b", CorrectionStatus.REVIEWED))
        save_entity_type_bucket(tmp_path, EntityTypeBucket(
            bucket="b1",
            entries=[EntityTypeEntry(name="X", inferred_type="concept")],
        ))
        rc = main(["stats", "--root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "source corrections" in out
        assert "entity-type buckets" in out
        assert "alias corrections" in out
        assert "pending" in out and "reviewed" in out

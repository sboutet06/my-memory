"""python -m corrections review — list pending correction files."""
from __future__ import annotations

from pathlib import Path

from corrections.__main__ import main
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

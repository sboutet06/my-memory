"""CLI-level tests for `python -m ingestion` batch behavior."""
from __future__ import annotations

from pathlib import Path

import pytest

from ingestion import ingest as ingest_mod
from ingestion.__main__ import main


@pytest.fixture
def fake_docling(monkeypatch: pytest.MonkeyPatch):
    def _stub(path: Path):
        return ({"schema": "docling", "name": path.name}, f"# {path.name}\n\nstub body", 5)

    monkeypatch.setattr(ingest_mod, "_run_docling", _stub)
    return _stub


def test_batch_surfaces_unsupported_files(
    tmp_path: Path, fake_docling, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "raw"
    folder.mkdir()
    (folder / "doc.pdf").write_bytes(b"%PDF-1.4\n")
    (folder / "note.pages").write_bytes(b"fake pages")

    rc = main([str(folder), "--store", str(tmp_path / "store")])
    out = capsys.readouterr().out

    assert rc == 0
    assert "[ingested] doc.pdf" in out
    assert "[unsupported] note.pages" in out


def test_batch_empty_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "raw"
    folder.mkdir()

    rc = main([str(folder), "--store", str(tmp_path / "store")])
    out = capsys.readouterr().out

    assert rc == 0
    assert "No files" in out


def test_single_file_unsupported_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "note.pages"
    f.write_bytes(b"x")

    rc = main([str(f), "--store", str(tmp_path / "store")])
    out = capsys.readouterr().out

    assert rc == 1
    assert "[unsupported] note.pages" in out

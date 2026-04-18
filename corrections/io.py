"""YAML read/write + idempotent merge for correction files."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from corrections.schemas import CorrectionStatus, Doubt, SourceCorrection

SOURCE_SUBDIR = "source"


def correction_path(root: Path, document_id: str) -> Path:
    return Path(root) / SOURCE_SUBDIR / f"{document_id}.yaml"


def load_source_correction(root: Path, document_id: str) -> Optional[SourceCorrection]:
    path = correction_path(root, document_id)
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text()) or {}
    return SourceCorrection.model_validate(data)


_TOP_ORDER = ("document_id", "original_filename", "status", "replaced_by",
              "doubts", "overrides")


def _ordered_dump(c: SourceCorrection) -> str:
    raw = c.model_dump(mode="json")
    ordered = {k: raw[k] for k in _TOP_ORDER if k in raw}
    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=100)


def save_source_correction(root: Path, correction: SourceCorrection) -> Path:
    path = correction_path(root, correction.document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ordered_dump(correction))
    return path


def merge_emitted_doubts(
    existing: Optional[SourceCorrection],
    emitted: list[Doubt],
    *,
    document_id: str,
    original_filename: str,
) -> SourceCorrection:
    """Merge newly-emitted doubts onto any existing correction file.

    Semantics:
      - doubts: replaced wholesale (pipeline is authoritative on its own uncertainty)
      - status: preserved (user decision sticks, even when new doubts arrive)
      - overrides / replaced_by: preserved (user edits never clobbered)
      - no existing file: create fresh with status=pending
    """
    if existing is None:
        return SourceCorrection(
            document_id=document_id,
            original_filename=original_filename,
            status=CorrectionStatus.PENDING,
            doubts=list(emitted),
        )
    return existing.model_copy(update={"doubts": list(emitted)})

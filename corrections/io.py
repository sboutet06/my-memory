"""YAML read/write + idempotent merge for correction files.

Writes use ruamel.yaml to emit inline comments next to user-editable
fields so humans never have to remember allowed values. Reads use the
same loader (safely loads our own output).
"""
from __future__ import annotations

import io as _io
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from corrections.schemas import CorrectionStatus, Doubt, SourceCorrection

SOURCE_SUBDIR = "source"


def correction_path(root: Path, document_id: str) -> Path:
    return Path(root) / SOURCE_SUBDIR / f"{document_id}.yaml"


_yaml = YAML(typ="safe", pure=True)
_yaml.default_flow_style = False
_yaml.allow_unicode = True
_yaml.width = 100

_yaml_rt = YAML()  # round-trip: preserves/authors comments
_yaml_rt.default_flow_style = False
_yaml_rt.allow_unicode = True
_yaml_rt.width = 100


def load_source_correction(root: Path, document_id: str) -> Optional[SourceCorrection]:
    path = correction_path(root, document_id)
    if not path.is_file():
        return None
    data = _yaml.load(path.read_text()) or {}
    return SourceCorrection.model_validate(data)


_TOP_ORDER = ("document_id", "original_filename", "status", "replaced_by",
              "doubts", "overrides")

# Inline hints shown next to user-editable fields.
_HINT_STATUS = "pending | reviewed"
_HINT_REPLACED_BY = "null | <another document_id> to mark this doc superseded"
_HINT_METADATA = "e.g. document_date: '2016-05-13' | extraction_quality: rich|degraded|empty"
_HINT_CONTENT_REPLACEMENTS = "list of {find: <str>, replace: <str>}"
_HINT_TAGS = "free-form list of strings, e.g. ['obsolete', 'draft']"


def _build_commented(c: SourceCorrection) -> CommentedMap:
    raw = c.model_dump(mode="json")
    doc = CommentedMap()
    for key in _TOP_ORDER:
        if key not in raw:
            continue
        doc[key] = raw[key]

    doc.yaml_add_eol_comment(_HINT_STATUS, "status")
    doc.yaml_add_eol_comment(_HINT_REPLACED_BY, "replaced_by")

    overrides = doc.get("overrides")
    if isinstance(overrides, dict):
        ov = CommentedMap(overrides)
        ov.yaml_add_eol_comment(_HINT_METADATA, "metadata")
        ov.yaml_add_eol_comment(_HINT_CONTENT_REPLACEMENTS, "content_replacements")
        ov.yaml_add_eol_comment(_HINT_TAGS, "tags")
        doc["overrides"] = ov

    return doc


def _dump_commented(doc: CommentedMap) -> str:
    buf = _io.StringIO()
    _yaml_rt.dump(doc, buf)
    return buf.getvalue()


def save_source_correction(root: Path, correction: SourceCorrection) -> Path:
    path = correction_path(root, correction.document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_commented(_build_commented(correction)))
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

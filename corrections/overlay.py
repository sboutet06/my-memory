"""Apply a SourceCorrection overlay onto stored metadata / content.

The overlay is read-side: `store/` stays immutable. Consumers call these
helpers after loading raw metadata / content to get the corrected view.
"""
from __future__ import annotations

from typing import Any, Optional

from corrections.schemas import SourceCorrection


def apply_metadata_overlay(
    metadata: dict[str, Any],
    correction: Optional[SourceCorrection],
) -> dict[str, Any]:
    out = dict(metadata)
    if correction is None:
        return out

    meta_over = correction.overrides.get("metadata") or {}
    out.update(meta_over)

    tag_over = correction.overrides.get("tags") or []
    if tag_over:
        existing_tags = list(out.get("tags") or [])
        for t in tag_over:
            if t not in existing_tags:
                existing_tags.append(t)
        out["tags"] = existing_tags

    if correction.replaced_by:
        out["replaced_by"] = correction.replaced_by

    return out


def apply_content_overlay(
    content: str,
    correction: Optional[SourceCorrection],
) -> str:
    if correction is None:
        return content
    replacements = correction.overrides.get("content_replacements") or []
    out = content
    for r in replacements:
        find = r.get("find")
        replace = r.get("replace", "")
        if not find:
            continue
        out = out.replace(find, replace)
    return out

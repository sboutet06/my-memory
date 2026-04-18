"""YAML read/write + idempotent merge for derivation-layer corrections.

File layout under the corrections root:
    derivation/entity_types/{bucket}.yaml
    derivation/aliases/{cluster_slug}.yaml

Every user-editable field carries an inline hint comment so humans
don't need to remember allowed values.
"""
from __future__ import annotations

import io as _io
import re
import unicodedata
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from corrections.derivation_schemas import (
    AliasCorrection,
    EntityTypeBucket,
    EntityTypeEntry,
)

DERIVATION_SUBDIR = "derivation"
ENTITY_TYPES_SUBDIR = "entity_types"
ALIASES_SUBDIR = "aliases"

_ALLOWED_TYPES_HINT = "person | organization | location | date | amount | document | concept"
_ACTION_HINT = "null (accept inferred) | merge | veto | split"
_CANONICAL_HINT = "null | pick a member name to win on merge"
_SPLIT_HINT = "optional partitions, e.g. [['A','B'], ['C']]"
_STATUS_HINT = "pending | reviewed"

_yaml = YAML(typ="safe", pure=True)
_yaml.default_flow_style = False
_yaml.allow_unicode = True
_yaml.width = 100

_yaml_rt = YAML()
_yaml_rt.default_flow_style = False
_yaml_rt.allow_unicode = True
_yaml_rt.width = 100


# ---------------------------- slug + paths -------------------------------


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def make_slug(s: str) -> str:
    """Accents stripped, lowercased, non-alphanumerics collapsed to `_`."""
    if not s:
        return "unnamed"
    decomp = unicodedata.normalize("NFKD", s)
    ascii_only = "".join(ch for ch in decomp if not unicodedata.combining(ch))
    lowered = ascii_only.casefold()
    slug = _SLUG_STRIP.sub("_", lowered).strip("_")
    return slug or "unnamed"


def entity_types_path(root: Path, bucket: str) -> Path:
    return Path(root) / DERIVATION_SUBDIR / ENTITY_TYPES_SUBDIR / f"{bucket}.yaml"


def alias_path(root: Path, cluster: str) -> Path:
    return Path(root) / DERIVATION_SUBDIR / ALIASES_SUBDIR / f"{cluster}.yaml"


# ------------------------------ writers ----------------------------------


def _dump(doc: CommentedMap) -> str:
    buf = _io.StringIO()
    _yaml_rt.dump(doc, buf)
    return buf.getvalue()


def _build_entity_type_yaml(b: EntityTypeBucket) -> CommentedMap:
    raw = b.model_dump(mode="json")
    doc = CommentedMap()
    doc["bucket"] = raw["bucket"]
    doc["status"] = raw["status"]
    doc.yaml_add_eol_comment(_STATUS_HINT, "status")

    entries = CommentedSeq()
    for i, e in enumerate(raw["entries"]):
        entry = CommentedMap()
        entry["name"] = e["name"]
        entry["inferred_type"] = e["inferred_type"]
        entry["override_type"] = e["override_type"]
        entry["evidence_docs"] = e["evidence_docs"]
        if i == 0:
            entry.yaml_add_eol_comment(_ALLOWED_TYPES_HINT, "override_type")
        entries.append(entry)
    doc["entries"] = entries
    return doc


def save_entity_type_bucket(root: Path, bucket: EntityTypeBucket) -> Path:
    p = entity_types_path(root, bucket.bucket)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_dump(_build_entity_type_yaml(bucket)))
    return p


def _build_alias_yaml(a: AliasCorrection) -> CommentedMap:
    raw = a.model_dump(mode="json")
    doc = CommentedMap()
    doc["cluster"] = raw["cluster"]
    doc["members"] = raw["members"]
    doc["status"] = raw["status"]
    doc.yaml_add_eol_comment(_STATUS_HINT, "status")
    doc["doubts"] = raw["doubts"]

    overrides = CommentedMap()
    overrides["action"] = raw["overrides"].get("action")
    overrides["canonical"] = raw["overrides"].get("canonical")
    overrides["split_groups"] = raw["overrides"].get("split_groups", [])
    overrides.yaml_add_eol_comment(_ACTION_HINT, "action")
    overrides.yaml_add_eol_comment(_CANONICAL_HINT, "canonical")
    overrides.yaml_add_eol_comment(_SPLIT_HINT, "split_groups")
    doc["overrides"] = overrides
    return doc


def save_alias_correction(root: Path, correction: AliasCorrection) -> Path:
    p = alias_path(root, correction.cluster)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_dump(_build_alias_yaml(correction)))
    return p


# ------------------------------ readers ----------------------------------


def load_entity_type_bucket(root: Path, bucket: str) -> Optional[EntityTypeBucket]:
    p = entity_types_path(root, bucket)
    if not p.is_file():
        return None
    return EntityTypeBucket.model_validate(_yaml.load(p.read_text()) or {})


def load_alias_correction(root: Path, cluster: str) -> Optional[AliasCorrection]:
    p = alias_path(root, cluster)
    if not p.is_file():
        return None
    return AliasCorrection.model_validate(_yaml.load(p.read_text()) or {})


def list_entity_type_buckets(root: Path) -> list[EntityTypeBucket]:
    directory = Path(root) / DERIVATION_SUBDIR / ENTITY_TYPES_SUBDIR
    if not directory.is_dir():
        return []
    out = []
    for y in sorted(directory.glob("*.yaml")):
        loaded = load_entity_type_bucket(root, y.stem)
        if loaded is not None:
            out.append(loaded)
    return out


def list_alias_corrections(root: Path) -> list[AliasCorrection]:
    directory = Path(root) / DERIVATION_SUBDIR / ALIASES_SUBDIR
    if not directory.is_dir():
        return []
    out = []
    for y in sorted(directory.glob("*.yaml")):
        loaded = load_alias_correction(root, y.stem)
        if loaded is not None:
            out.append(loaded)
    return out


# ------------------------------ mergers ----------------------------------


def merge_entity_type_bucket(
    existing: Optional[EntityTypeBucket],
    fresh_entries: list[EntityTypeEntry],
    *,
    bucket: str,
) -> EntityTypeBucket:
    """Preserve user-set `override_type` per name; refresh everything else.

    Entries absent from `fresh_entries` are dropped (pipeline authoritative
    on who's in the bucket).
    """
    existing_overrides: dict[str, str] = (
        existing.overrides_by_name() if existing else {}
    )
    merged_entries = []
    for fe in fresh_entries:
        user_type = existing_overrides.get(fe.name)
        merged_entries.append(fe.model_copy(update={"override_type": user_type}))
    return EntityTypeBucket(
        bucket=bucket,
        status=existing.status if existing else EntityTypeBucket.model_fields["status"].default,
        entries=merged_entries,
    )


def merge_alias_correction(
    existing: Optional[AliasCorrection],
    fresh: AliasCorrection,
) -> AliasCorrection:
    """Members + doubts refreshed from `fresh`; status + overrides preserved."""
    if existing is None:
        return fresh
    return fresh.model_copy(update={
        "status": existing.status,
        "overrides": existing.overrides,
    })

"""YAML emit/load/apply for conflict corrections.

File layout:
    corrections/derivation/conflicts/<subject_slug>__<predicate>.yaml

One file per detected Conflict. The pipeline emits it; the human edits
the `resolution:` section and flips `status: reviewed`; then
`apply_conflict_corrections` writes the resolution back to the FactStore.
"""
from __future__ import annotations

import io as _io
import logging
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from corrections.derivation_io import make_slug
from corrections.derivation_schemas import (
    ConflictCorrection,
    ConflictFactEntry,
    ConflictResolution,
)
from facts.models import Conflict
from facts.store import FactStore

logger = logging.getLogger(__name__)

CONFLICTS_SUBDIR = Path("derivation") / "conflicts"

_yaml_rt = YAML()
_yaml_rt.default_flow_style = False
_yaml_rt.allow_unicode = True
_yaml_rt.width = 100

_yaml_safe = YAML(typ="safe", pure=True)
_yaml_safe.default_flow_style = False
_yaml_safe.allow_unicode = True


# ------------------------------ paths ------------------------------------


def conflict_path(corrections_root: Path, conflict: Conflict) -> Path:
    subj_slug = make_slug(conflict.subject_id)[:40]
    pred_slug = make_slug(conflict.predicate)[:20]
    return corrections_root / CONFLICTS_SUBDIR / f"{subj_slug}__{pred_slug}.yaml"


# ------------------------------ emit -------------------------------------


def emit_conflict_yaml(
    conflict: Conflict,
    store: FactStore,
    corrections_root: Path,
) -> Path:
    """Write a YAML conflict correction file (idempotent — does not overwrite)."""
    path = conflict_path(corrections_root, conflict)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        return path

    doc = CommentedMap()
    doc["conflict_id"] = conflict.id
    doc["subject_id"] = conflict.subject_id
    doc["predicate"] = conflict.predicate
    doc["status"] = "open"
    doc.yaml_add_eol_comment("open | reviewed", "status")

    facts_seq = CommentedSeq()
    for fid in conflict.competing_fact_ids:
        fact = store.get_fact(fid)
        entry = CommentedMap()
        entry["fact_id"] = fid
        entry["value"] = fact.canonical_value if fact else ""
        entry["source_doc"] = fact.source_doc_id if fact else ""
        facts_seq.append(entry)
    doc["competing_facts"] = facts_seq

    # Resolution section — human edits one of the three options
    res = CommentedMap()
    res["winner"] = None
    res.yaml_add_eol_comment(
        "set to a fact_id above to pick one as correct", "winner"
    )
    res["coexist"] = False
    res.yaml_add_eol_comment(
        "set true if multiple values are simultaneously valid", "coexist"
    )
    order_seq: CommentedSeq = CommentedSeq()
    order_seq.yaml_set_start_comment(
        "list fact_ids from oldest → newest for temporal supersession"
    )
    res["temporal_supersede_order"] = order_seq
    doc["resolution"] = res

    buf = _io.StringIO()
    _yaml_rt.dump(doc, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


# ------------------------------ load -------------------------------------


def load_conflict_yaml(path: Path) -> ConflictCorrection:
    raw = _yaml_safe.load(path.read_text(encoding="utf-8"))
    res_raw = raw.get("resolution") or {}
    resolution = None
    if res_raw:
        winner = res_raw.get("winner")
        coexist = bool(res_raw.get("coexist", False))
        order = list(res_raw.get("temporal_supersede_order") or [])
        if winner or coexist or order:
            resolution = ConflictResolution(
                winner=winner,
                coexist=coexist,
                temporal_supersede_order=order,
            )

    facts = [
        ConflictFactEntry(
            fact_id=e.get("fact_id", ""),
            value=e.get("value", ""),
            source_doc=e.get("source_doc", ""),
        )
        for e in (raw.get("competing_facts") or [])
    ]
    return ConflictCorrection(
        conflict_id=raw["conflict_id"],
        subject_id=raw["subject_id"],
        predicate=raw["predicate"],
        status=raw.get("status", "open"),
        competing_facts=facts,
        resolution=resolution,
    )


# ------------------------------ write ------------------------------------


def write_conflict_yaml(cc: ConflictCorrection, path: Path) -> None:
    """Write a ConflictCorrection back to YAML (for programmatic updates)."""
    doc = CommentedMap()
    doc["conflict_id"] = cc.conflict_id
    doc["subject_id"] = cc.subject_id
    doc["predicate"] = cc.predicate
    doc["status"] = cc.status
    doc.yaml_add_eol_comment("open | reviewed", "status")

    facts_seq = CommentedSeq()
    for f in cc.competing_facts:
        entry = CommentedMap()
        entry["fact_id"] = f.fact_id
        entry["value"] = f.value
        entry["source_doc"] = f.source_doc
        facts_seq.append(entry)
    doc["competing_facts"] = facts_seq

    if cc.resolution is not None:
        res = CommentedMap()
        res["winner"] = cc.resolution.winner
        res["coexist"] = cc.resolution.coexist
        res["temporal_supersede_order"] = list(cc.resolution.temporal_supersede_order)
        doc["resolution"] = res

    buf = _io.StringIO()
    _yaml_rt.dump(doc, buf)
    path.write_text(buf.getvalue(), encoding="utf-8")


# ------------------------------ apply ------------------------------------


def apply_conflict_corrections(
    corrections_root: Path,
    store: FactStore,
    apply: bool = False,
) -> list[str]:
    """Read all conflict YAML files and apply reviewed resolutions to the store.

    Returns list of conflict_ids that were (or would be) updated.
    When apply=False (dry-run) store is not modified.
    """
    conflicts_dir = corrections_root / CONFLICTS_SUBDIR
    if not conflicts_dir.exists():
        return []

    updated: list[str] = []
    for yaml_path in sorted(conflicts_dir.glob("*.yaml")):
        try:
            cc = load_conflict_yaml(yaml_path)
        except Exception as exc:
            logger.warning("conflict_io: cannot load %s: %s", yaml_path, exc)
            continue

        if cc.status != "reviewed" or cc.resolution is None:
            continue

        conflict = store.get_conflict(cc.conflict_id)
        if conflict is None:
            logger.warning("conflict_io: conflict %s not in store, skipping", cc.conflict_id)
            continue

        res = cc.resolution
        if res.temporal_supersede_order:
            new_status = "resolved_temporally"
        else:
            new_status = "resolved_manually"

        resolution_dict: dict = {}
        if res.winner:
            resolution_dict["winner"] = res.winner
        if res.coexist:
            resolution_dict["coexist"] = True
        if res.temporal_supersede_order:
            resolution_dict["temporal_supersede_order"] = res.temporal_supersede_order

        updated.append(cc.conflict_id)
        if not apply:
            logger.info("dry-run: would resolve conflict %s as %s", cc.conflict_id, new_status)
            continue

        updated_conflict = Conflict(
            subject_id=conflict.subject_id,
            predicate=conflict.predicate,
            competing_fact_ids=conflict.competing_fact_ids,
            status=new_status,
            resolution=resolution_dict,
        )
        all_conflicts = [
            c if c.id != cc.conflict_id else updated_conflict
            for c in store.all_conflicts()
        ]
        store.replace_conflicts(all_conflicts)
        logger.info("applied resolution for conflict %s", cc.conflict_id)

    return updated

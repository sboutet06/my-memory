"""`replaced_by` correction wiring — Phase 8b.1 (8.3).

When a source-correction YAML carries `replaced_by: <other_doc_id>`, the
replaced document's facts inherit a constrained `valid_to` and any
Conflict between (replaced_doc_facts, replacement_doc_facts) gets
auto-resolved as `resolved_temporally` with the replacement as winner.

Idempotent: re-running with no new replacements is a no-op.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from corrections.io import SOURCE_SUBDIR, load_source_correction
from facts.models import Conflict, Fact
from facts.predicates import PredicateRegistry
from facts.store import FactStore

logger = logging.getLogger(__name__)


@dataclass
class ReplacementReport:
    facts_updated: int = 0
    conflicts_resolved: int = 0


def _doc_date(store_root: Path, document_id: str) -> date | None:
    """Read `document_date` from `store_root/<doc_id>/metadata.json`.

    Returns None if metadata missing, unreadable, or document_date null.
    """
    meta_path = store_root / document_id / "metadata.json"
    if not meta_path.is_file():
        logger.warning("metadata missing for %s — skipping replacement", document_id)
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("metadata unreadable for %s: %s", document_id, exc)
        return None
    raw = data.get("document_date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date() if "T" in raw else date.fromisoformat(raw)
    except ValueError:
        logger.warning("bad document_date %r for %s", raw, document_id)
        return None


def _replacement_chains(corrections_root: Path) -> Iterable[tuple[str, str]]:
    """Yield (old_doc_id, new_doc_id) for every YAML with replaced_by set."""
    source_dir = corrections_root / SOURCE_SUBDIR
    if not source_dir.is_dir():
        return
    for yaml_path in sorted(source_dir.glob("*.yaml")):
        doc_id = yaml_path.stem
        corr = load_source_correction(corrections_root, doc_id)
        if corr is None or not corr.replaced_by:
            continue
        yield (corr.document_id, corr.replaced_by)


def _pick_valid_to(new_fact: Fact, replacement_doc_date: date | None) -> date | None:
    """The valid_to we want to pin onto the OLD fact.

    Preference order:
      1. new_fact.valid_from − 1 day (most precise)
      2. replacement_doc_date − 1 day (fallback when new fact undated)
      3. None (give up; caller will skip)
    """
    if new_fact.valid_from is not None:
        return new_fact.valid_from - timedelta(days=1)
    if replacement_doc_date is not None:
        return replacement_doc_date - timedelta(days=1)
    return None


def apply_replacements(
    store: FactStore,
    *,
    corrections_root: Path,
    store_root: Path,
    registry: PredicateRegistry,
) -> ReplacementReport:
    """Apply all `replaced_by` chains to facts + conflicts.

    For each correction with replaced_by:
      - For every old-doc fact, find the competing new-doc fact (same
        subject_id, predicate). If the predicate is time_varying and
        old.valid_to is None, set old.valid_to per `_pick_valid_to`.
      - For every Conflict whose competing set contains BOTH old + new
        facts, mark resolved_temporally with new as winner.

    Returns a ReplacementReport with the counts touched.
    """
    report = ReplacementReport()

    chains = list(_replacement_chains(corrections_root))
    if not chains:
        return report

    # Index facts by source_doc_id for O(1) lookup.
    facts_by_doc: dict[str, list[Fact]] = {}
    for f in store.all_facts():
        facts_by_doc.setdefault(f.source_doc_id, []).append(f)

    facts_by_id: dict[str, Fact] = {f.id: f for f in store.all_facts()}
    fact_dirty = False

    conflicts_by_id: dict[str, Conflict] = {c.id: c for c in store.all_conflicts()}
    conflict_dirty = False

    for old_doc_id, new_doc_id in chains:
        old_facts = facts_by_doc.get(old_doc_id, [])
        new_facts = facts_by_doc.get(new_doc_id, [])
        if not old_facts:
            continue
        if not new_facts:
            logger.info(
                "replaced_by %s → %s: no facts on new doc, skipping",
                old_doc_id, new_doc_id,
            )
            continue

        new_doc_date = _doc_date(store_root, new_doc_id)

        # Pair by (subject_id, predicate).
        new_by_key: dict[tuple[str, str], Fact] = {
            (f.subject_id, f.predicate): f for f in new_facts
        }

        for old in old_facts:
            new = new_by_key.get((old.subject_id, old.predicate))
            if new is None:
                continue

            pred = registry.get(old.predicate)

            # 1. Constrain valid_to on time_varying facts.
            if pred.time_varying and old.valid_to is None:
                vto = _pick_valid_to(new, new_doc_date)
                if vto is not None:
                    facts_by_id[old.id] = old.model_copy(update={"valid_to": vto})
                    fact_dirty = True
                    report.facts_updated += 1

            # 2. Resolve Conflict if it spans this pair.
            for conflict in conflicts_by_id.values():
                if conflict.status != "open":
                    continue
                if (
                    old.id in conflict.competing_fact_ids
                    and new.id in conflict.competing_fact_ids
                ):
                    conflicts_by_id[conflict.id] = conflict.model_copy(update={
                        "status": "resolved_temporally",
                        "resolution": {
                            "winner_fact_id": new.id,
                            "loser_fact_id": old.id,
                            "source": "replaced_by",
                            "old_doc_id": old_doc_id,
                            "new_doc_id": new_doc_id,
                        },
                    })
                    conflict_dirty = True
                    report.conflicts_resolved += 1

    if fact_dirty:
        store.replace_facts(list(facts_by_id.values()))
        logger.info(
            "replaced_by: %d fact(s) updated", report.facts_updated,
        )
    if conflict_dirty:
        store.replace_conflicts(list(conflicts_by_id.values()))
        logger.info(
            "replaced_by: %d conflict(s) resolved", report.conflicts_resolved,
        )

    return report

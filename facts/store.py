"""JSONL-backed FactStore — append-only, reloads on init.

One file per record type: facts.jsonl, claims.jsonl, conflicts.jsonl.
Each line is a complete JSON object. In-memory index (dict[id, model])
is rebuilt on every FactStore instantiation from the on-disk files.

Lesson 2026-04-15: JSONL event streams beat sqlite for short-lived audit
trails — greppable, tailable, diffable, jq-able, no schema migrations.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from facts.models import Claim, Conflict, Fact

logger = logging.getLogger(__name__)


class DuplicateIDError(ValueError):
    """Raised when appending a record whose id already exists in the store."""


class FactStore:
    """Append-only JSONL store for Facts, Claims, and Conflicts.

    Thread-safety: single-writer assumed (same process). Multiple
    readers safe after construction (in-memory index is immutable once
    built). Do NOT share a FactStore instance across async tasks without
    external locking.
    """

    def __init__(self, store_dir: Path) -> None:
        self._dir = store_dir
        self._facts: dict[str, Fact] = {}
        self._claims: dict[str, Claim] = {}
        self._conflicts: dict[str, Conflict] = {}
        self._load()

    # ------------------------------------------------------------------ paths

    @property
    def _facts_path(self) -> Path:
        return self._dir / "facts.jsonl"

    @property
    def _claims_path(self) -> Path:
        return self._dir / "claims.jsonl"

    @property
    def _conflicts_path(self) -> Path:
        return self._dir / "conflicts.jsonl"

    # ------------------------------------------------------------------ load

    def _load(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        specs = [
            (self._facts_path, self._facts, Fact),
            (self._claims_path, self._claims, Claim),
            (self._conflicts_path, self._conflicts, Conflict),
        ]
        for path, target, cls in specs:
            if not path.exists():
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = cls.model_validate_json(line)
                    target[obj.id] = obj  # type: ignore[index]
                except Exception as exc:
                    logger.warning("%s line %d invalid, skipping: %s", path.name, lineno, exc)

    # ------------------------------------------------------------------ facts

    def append_fact(self, fact: Fact) -> None:
        if fact.id in self._facts:
            raise DuplicateIDError(f"Fact {fact.id!r} already exists")
        self._facts[fact.id] = fact
        with self._facts_path.open("a", encoding="utf-8") as fh:
            fh.write(fact.model_dump_json() + "\n")

    def get_fact(self, fact_id: str) -> Fact | None:
        return self._facts.get(fact_id)

    def facts_for_subject(self, subject_id: str) -> list[Fact]:
        return [f for f in self._facts.values() if f.subject_id == subject_id]

    def all_facts(self) -> Iterator[Fact]:
        return iter(self._facts.values())

    @property
    def fact_count(self) -> int:
        return len(self._facts)

    # ------------------------------------------------------------------ claims

    def append_claim(self, claim: Claim) -> None:
        if claim.id in self._claims:
            raise DuplicateIDError(f"Claim {claim.id!r} already exists")
        self._claims[claim.id] = claim
        with self._claims_path.open("a", encoding="utf-8") as fh:
            fh.write(claim.model_dump_json() + "\n")

    def get_claim(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def claims_for_fact(self, fact_id: str) -> list[Claim]:
        return [c for c in self._claims.values() if c.fact_id == fact_id]

    @property
    def claim_count(self) -> int:
        return len(self._claims)

    # --------------------------------------------------------------- conflicts

    def append_conflict(self, conflict: Conflict) -> None:
        if conflict.id in self._conflicts:
            raise DuplicateIDError(f"Conflict {conflict.id!r} already exists")
        self._conflicts[conflict.id] = conflict
        with self._conflicts_path.open("a", encoding="utf-8") as fh:
            fh.write(conflict.model_dump_json() + "\n")

    def get_conflict(self, conflict_id: str) -> Conflict | None:
        return self._conflicts.get(conflict_id)

    def open_conflicts(self) -> list[Conflict]:
        return [c for c in self._conflicts.values() if c.status == "open"]

    @property
    def conflict_count(self) -> int:
        return len(self._conflicts)

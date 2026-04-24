"""Predicate registry — semantic contracts for facts.

Packs declare predicates via a `predicates: tuple[Predicate, ...]` attribute.
Core merges all pack predicates into one registry at startup.

Unknown predicates default to time_varying=False, allow_multi=False, which
means two different values for the same (subject, predicate) pair produce a
Conflict (D2 — unknown-variance defaults to Conflict, never silent merge).
"""
from __future__ import annotations

import logging
from typing import Iterator

from facts.models import Predicate

logger = logging.getLogger(__name__)


class PredicateRegistry:
    """Maps predicate names to their semantic contracts.

    Thread-safety: build once at startup, read-only thereafter.
    """

    def __init__(self) -> None:
        self._registry: dict[str, Predicate] = {}

    def register(self, predicate: Predicate) -> None:
        if predicate.name in self._registry:
            logger.debug("predicate %r overwritten in registry", predicate.name)
        self._registry[predicate.name] = predicate

    def get(self, name: str) -> Predicate:
        if name in self._registry:
            return self._registry[name]
        return Predicate(name=name, time_varying=False, allow_multi=False)

    def all(self) -> Iterator[Predicate]:
        return iter(self._registry.values())

    @classmethod
    def from_packs(cls, packs: list) -> "PredicateRegistry":
        registry = cls()
        for pack in packs:
            for predicate in getattr(pack, "predicates", ()):
                registry.register(predicate)
        return registry

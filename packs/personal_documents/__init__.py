"""personal_documents pack — any document a person accumulates.

Absorbs invoices, contracts, IDs, payslips, medical records, recipes,
vehicle orders, etc. Declares additional entity types that the core
taxonomy intentionally does not carry (core stays domain-agnostic).

For V0, the pack is purely a type-extension contributor. Document-
specific schemas (Transaction, Prescription, Payslip, …) and
extractors are layered in later phases when real needs surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import logging

from facts.models import FactResult, Predicate
from facts.store import DuplicateIDError, FactStore
from packs.personal_documents.focus import extraction_hints as _extraction_hints
from packs.personal_documents.injector import (
    LOW_SIGNAL_TYPES,
    inject_structured as _inject_structured,
    plan_transaction_facts as _plan_transaction_facts,
    summary_extras_for_doc as _summary_extras_for_doc,
)
from packs.personal_documents.router import (
    detect_doc_kind,
    extract_structured as _extract_structured,
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PersonalDocumentsPack:
    name: str = "personal_documents"
    version: str = "0.2.0"

    # Declared types — grouped by life domain for reviewability.
    # Changes to this list change the LLM's extraction prompt, which is
    # a non-trivial behavior change; add types only when a real document
    # reveals that core+current-pack cannot express the observed entity.
    declared_types: tuple[str, ...] = (
        # Things a person owns or interacts with
        "object",            # invoice line-items, insurance-covered goods
        "vehicle",           # cars, bikes — referenced across insurance/tax
        "property",          # real estate parcels, homes
        "animal",            # pets (vet, insurance, contracts)

        # Healthcare
        "medication",
        "diagnosis",
        "procedure",         # medical procedure / exam
        "body_part",         # anatomical region, organ, fluid
        "medical_provider",  # individual clinician (orgs stay `organization`)

        # Work
        "employer",          # job-context organization (orgs stay `organization` otherwise)
        "role",              # job title, professional role
        "skill",             # competency, qualification

        # Finance (beyond core `amount`)
        "account",           # bank/investment account
        "transaction_category",

        # Food / recipes
        "ingredient",
        "dish",
        "nutrient",
        "cooking_technique",

        # Life events + activities
        "event",             # marriage, birth, hospitalisation, purchase, trip
        "activity",          # hobby, sport, course
        "trip",
        "accommodation",
    )

    # Entity types this pack injects as retrieval-infra; core hides them
    # from Profile/Catalog and doc-summary views.
    low_signal_types: tuple[str, ...] = LOW_SIGNAL_TYPES

    # Semantic contracts for predicates this pack produces.
    # time_varying=True → new value supersedes old (Phase 8 supersession engine).
    # allow_multi=True  → multiple values coexist; no Conflict emitted.
    # Unknown predicates default to time_varying=False, allow_multi=False → Conflict.
    predicates: tuple[Predicate, ...] = (
        Predicate(name="transaction", time_varying=False, allow_multi=True,
                  description="bank/card transaction; multiple per account are expected"),
        Predicate(name="address", time_varying=True, allow_multi=False,
                  description="residential or professional address; changes over time"),
        Predicate(name="employer", time_varying=True, allow_multi=False,
                  description="current employer; changes over time"),
        Predicate(name="role", time_varying=True, allow_multi=False,
                  description="job title or professional role; changes over time"),
        Predicate(name="birthdate", time_varying=False, allow_multi=False,
                  description="date of birth; invariant — two different values = Conflict"),
        Predicate(name="marital_status", time_varying=True, allow_multi=False,
                  description="marital status; changes over time"),
        Predicate(name="salary", time_varying=True, allow_multi=False,
                  description="gross/net salary; changes over time"),
        Predicate(name="passport_number", time_varying=False, allow_multi=False,
                  description="passport document number; invariant per issuance"),
        Predicate(name="social_security_id", time_varying=False, allow_multi=False,
                  description="national social security / NIR number; invariant"),
    )

    def matches(self, metadata: dict, content_md: str) -> bool:
        """Claim every document for the taxonomy-augmentation purpose.

        Structured extraction is routed separately via `extract_structured`
        and returns None for docs the pack has no extractor for; no need
        to gate here.
        """
        return True

    def extract_structured(self, metadata: dict, content_md: str) -> Optional[dict]:
        """Return structured records for docs this pack knows how to parse.

        Shape:
            {"kind": "<known_kind>", "<kind>_key": [Record, ...]}
        or None when no extractor matches.
        """
        return _extract_structured(metadata, content_md)

    async def inject_structured(self, rag, result: dict) -> dict:
        """Write the records produced by `extract_structured` into the graph."""
        return await _inject_structured(rag, result)

    async def summary_extras_for_doc(self, rag, doc_id: str) -> list[str]:
        """Retrieval-friendly extras to splice into `doc_id`'s summary chunk."""
        return await _summary_extras_for_doc(rag, doc_id)

    def inject_facts(self, rag, facts_store: FactStore, result: dict) -> FactResult:
        """Pack hook: write Facts + Claims derived from extract_structured output.

        Called by facts.orchestrator.run_inject_facts for every registered
        pack. DuplicateIDError on repeated runs is swallowed — idempotent.
        Returns the FactResult produced (written or skipped) for inspection.
        """
        kind = result.get("kind")
        if kind != "bank_statement":
            return FactResult()

        transactions = result.get("transactions") or []
        fact_result = _plan_transaction_facts(transactions)

        for fact in fact_result.facts:
            try:
                facts_store.append_fact(fact)
            except DuplicateIDError:
                _logger.debug("fact %s already in store, skipping", fact.id)

        for claim in fact_result.claims:
            try:
                facts_store.append_claim(claim)
            except DuplicateIDError:
                _logger.debug("claim %s already in store, skipping", claim.id)

        return fact_result

    def extraction_hints(self, metadata: dict) -> list[str]:
        """Focus entity types for this doc based on its `doc_context` tags.

        Empty list → no hint (LLM falls back to the full taxonomy). Core
        prepends a single `[EXTRACTION FOCUS: ...]` line when non-empty.
        """
        return _extraction_hints(metadata)


PACK = _PersonalDocumentsPack()

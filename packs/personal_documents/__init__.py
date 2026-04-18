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

from packs.personal_documents.injector import (
    LOW_SIGNAL_TYPES,
    inject_structured as _inject_structured,
    summary_extras_for_doc as _summary_extras_for_doc,
)
from packs.personal_documents.router import (
    detect_doc_kind,
    extract_structured as _extract_structured,
)


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


PACK = _PersonalDocumentsPack()

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


@dataclass(frozen=True)
class _PersonalDocumentsPack:
    name: str = "personal_documents"
    version: str = "0.1.0"

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

    def matches(self, metadata: dict, content_md: str) -> bool:
        """V0 behavior: claim every document.

        The pack augments the extraction taxonomy corpus-wide; it does
        not yet route per-document to pack-specific extractors. When
        those exist (later phase), `matches` will become selective.
        """
        return True


PACK = _PersonalDocumentsPack()

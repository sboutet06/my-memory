"""LLM-based predicate extractors for the personal_documents pack — Phase 8b.5.

Three Fact-emitting extractors (address, birthdate, employer) that
operate on free-text document content rather than the deterministic
table parser used by bank Transaction.

Architecture:
1. The caller (extraction CLI) decides whether a doc is in the trigger
   set for a given predicate (via `should_run_for_doc`).
2. If yes, the caller invokes the extractor with the doc's text and
   `llm_func` (typically `extraction.llm.make_llm_func(config)` so the
   8b.3 fingerprint cache is wired in for free).
3. The extractor sends a schema-constrained prompt, parses the JSON
   response, post-validates each item via deterministic regex, and
   emits a `FactResult`.

Confidence mapping per charter §3.2 (categorical):
- Post-validation passes → `ConfidenceLevel.LLM_HIGH`.
- LLM produced an item but validation failed → `ConfidenceLevel.LLM_LOW`
  (still emitted — visible to the user via the API, conflict detector
  picks it up so the user can override via correction YAML).
- Bank deterministic remains `ConfidenceLevel.DETERMINISTIC`
  (unchanged, lives in `injector.plan_transaction_facts`).

Subject identity:
- Map LLM-supplied `entity_name` to a stable subject_id =
  `entity:<slug>`. The slug is NFKD-folded + lowercased + non-alnum
  stripped, so `« Jean-Pierre Dupont »` and `"jean pierre dupont"`
  resolve to the same subject. A future Phase 9 cleanup can swap this
  for a real graph-entity lookup; v0.5 keeps it simple.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Optional

from facts.models import Claim, ConfidenceLevel, Fact, FactResult

logger = logging.getLogger(__name__)

_PACK_VERSION = "0.3.0"  # bumped from 0.2.0 (8b.5 adds predicate extractors)

LLMFunc = Callable[..., Awaitable[str]]


# ============================================================================
# Subject-id resolution
# ============================================================================


def _slug(name: str) -> str:
    """NFKD-fold → strip combining marks → lowercase → keep [a-z0-9-]."""
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", name)
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = no_marks.lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


def _subject_id(entity_name: str) -> str:
    slug = _slug(entity_name)
    if not slug:
        slug = "unknown"
    return f"entity:{slug}"


# ============================================================================
# Doc-trigger sets
# ============================================================================


_ADDRESS_TRIGGER_TAGS = frozenset({
    "proposition_assurance", "invoice", "tax_notice", "identity",
    "compromis_vente", "bulletin_paie", "proof_of_address",
    "administrative", "legal", "healthcare",
})

_BIRTHDATE_TRIGGER_TAGS = frozenset({
    "identity", "passport", "tax_notice", "bulletin_paie",
    "birth_certificate", "healthcare",
})

_EMPLOYER_TRIGGER_TAGS = frozenset({
    "bulletin_paie", "contrat_travail", "tax_notice",
    "cv", "attestation_emploi",
})


def should_run_address_for(metadata: dict) -> bool:
    tags = set(metadata.get("doc_context") or [])
    return bool(tags & _ADDRESS_TRIGGER_TAGS)


def should_run_birthdate_for(metadata: dict) -> bool:
    tags = set(metadata.get("doc_context") or [])
    return bool(tags & _BIRTHDATE_TRIGGER_TAGS)


def should_run_employer_for(metadata: dict) -> bool:
    tags = set(metadata.get("doc_context") or [])
    return bool(tags & _EMPLOYER_TRIGGER_TAGS)


# ============================================================================
# Post-validators
# ============================================================================


# EU postal address — permissive across FR / BE / CH / DE / NL etc.
# Requires a street-number prefix (1-4 digits), some text, and a 4-5
# digit postal code followed by a city. Letters in postal code (NL/UK)
# allowed via the optional `[A-Z]{0,2}` block.
_ADDRESS_RE = re.compile(
    r"^\s*\d{1,4}[\w\s,\.\-'À-ÿ]+?\d{4,5}\s*[A-Z]{0,2}\s+[\w\-'À-ÿ][\w\s\-'À-ÿ]*$",
)

# ISO date (YYYY-MM-DD).
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_address(address_text: str) -> bool:
    if not address_text:
        return False
    # Collapse newlines into single spaces — addresses often span 2 lines.
    text = " ".join(address_text.split())
    return bool(_ADDRESS_RE.match(text))


def validate_birthdate(birthdate_iso: str) -> bool:
    if not birthdate_iso or not _DATE_RE.match(birthdate_iso):
        return False
    try:
        d = date.fromisoformat(birthdate_iso)
    except ValueError:
        return False
    return 1900 <= d.year <= datetime.now().year


def validate_employer_name(name: str) -> bool:
    return bool(name) and bool(name.strip())


# ============================================================================
# Canonicalizers
# ============================================================================


def _canonical_address(components: dict[str, Any], fallback_text: str) -> str:
    """`<street>, <postal_code> <city>` when all three present; else folded fallback."""
    street = (components.get("street") or "").strip()
    postal = (components.get("postal_code") or "").strip()
    city = (components.get("city") or "").strip()
    if street and postal and city:
        return f"{street}, {postal} {city}"
    return " ".join((fallback_text or "").split())


def _canonical_birthdate(iso: str) -> str:
    return iso.strip()


def _canonical_employer(name: str) -> str:
    return " ".join(name.split())


# ============================================================================
# JSON parsing (tolerant)
# ============================================================================


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_llm_json(raw: str) -> list[dict]:
    """Strip ``` fences if present, parse a JSON array. Return [] on failure.

    The lesson "JSON parsing from LLMs needs a multi-stage pipeline"
    (2026-04-12) applies — bare json.loads fails on most non-frontier
    models. v0.5 keeps it to fence-strip + parse; if 8b.7 gate reveals
    more failures, add trailing-comma / single-quote repair.
    """
    if not raw:
        return []
    body = _FENCE_RE.sub("", raw).strip()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.warning("LLM JSON parse failed: %s (raw[:120]=%r)", exc, raw[:120])
        return []
    if not isinstance(parsed, list):
        logger.warning("LLM JSON not a list: %s", type(parsed).__name__)
        return []
    return [item for item in parsed if isinstance(item, dict)]


# ============================================================================
# Prompts
# ============================================================================


_ADDRESS_PROMPT = """Extract every postal address mentioned in the document, with the entity (person OR organization) it refers to.

Output STRICT JSON only — a top-level array (no prose, no markdown, no code fences).
Each item:
{
  "entity_name": "<person or organization name>",
  "address_text": "<full address as it appears, on one line>",
  "components": {"street": "<n + street>", "postal_code": "<4-5 digit code>", "city": "<city>"},
  "role": "current" | "former" | "unknown"
}

If no address is mentioned, output exactly: []

Document:
---
{doc_text}
---
"""


_BIRTHDATE_PROMPT = """Extract the date of birth of every PERSON named in the document.

Output STRICT JSON only — a top-level array.
Each item:
{
  "entity_name": "<person full name>",
  "birthdate_iso": "YYYY-MM-DD"
}

If no birthdate is mentioned, output exactly: []

Document:
---
{doc_text}
---
"""


_EMPLOYER_PROMPT = """Extract employment relationships from the document. For each person mentioned with an employer:

Output STRICT JSON only — a top-level array.
Each item:
{
  "employee_name": "<full name>",
  "employer_name": "<organization name>",
  "period_start_iso": "YYYY-MM-DD" or null,
  "period_end_iso": "YYYY-MM-DD" or null,
  "role": "<job title or null>"
}

If no employment relationship is mentioned, output exactly: []

Document:
---
{doc_text}
---
"""


# ============================================================================
# Extractors
# ============================================================================


def _make_fact_and_claim(
    *,
    subject_id: str,
    predicate: str,
    canonical_value: str,
    value: Any,
    source_doc_id: str,
    valid_from: Optional[date],
    valid_to: Optional[date],
    confidence: ConfidenceLevel,
    source_location: str,
) -> tuple[Fact, Claim]:
    fact = Fact(
        subject_id=subject_id,
        predicate=predicate,
        canonical_value=canonical_value,
        value=value,
        source_doc_id=source_doc_id,
        valid_from=valid_from,
        valid_to=valid_to,
        confidence=confidence,
    )
    claim = Claim(
        fact_id=fact.id,
        source_doc_id=source_doc_id,
        source_location=source_location,
        extractor=f"pack:{predicate}@{_PACK_VERSION}",
        confidence=confidence,
    )
    return fact, claim


def _parse_optional_date(raw: Optional[str]) -> Optional[date]:
    if not raw or not _DATE_RE.match(raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


async def extract_address_facts(
    *,
    content_md: str,
    source_doc_id: str,
    llm_func: LLMFunc,
    document_date: Optional[date] = None,
) -> FactResult:
    raw = await llm_func(_ADDRESS_PROMPT.replace("{doc_text}", content_md or ""))
    items = parse_llm_json(raw)

    facts: list[Fact] = []
    claims: list[Claim] = []
    for idx, item in enumerate(items):
        entity_name = (item.get("entity_name") or "").strip()
        address_text = (item.get("address_text") or "").strip()
        components = item.get("components") or {}
        if not entity_name or not address_text:
            continue

        passes = validate_address(address_text)
        confidence = ConfidenceLevel.LLM_HIGH if passes else ConfidenceLevel.LLM_LOW
        canonical = _canonical_address(components, address_text)

        fact, claim = _make_fact_and_claim(
            subject_id=_subject_id(entity_name),
            predicate="address",
            canonical_value=canonical,
            value={"text": address_text, "components": components, "role": item.get("role")},
            source_doc_id=source_doc_id,
            valid_from=document_date,
            valid_to=None,
            confidence=confidence,
            source_location=f"address:{idx}",
        )
        facts.append(fact)
        claims.append(claim)

    return FactResult(facts=facts, claims=claims)


async def extract_birthdate_facts(
    *,
    content_md: str,
    source_doc_id: str,
    llm_func: LLMFunc,
) -> FactResult:
    raw = await llm_func(_BIRTHDATE_PROMPT.replace("{doc_text}", content_md or ""))
    items = parse_llm_json(raw)

    facts: list[Fact] = []
    claims: list[Claim] = []
    for idx, item in enumerate(items):
        entity_name = (item.get("entity_name") or "").strip()
        birthdate_iso = (item.get("birthdate_iso") or "").strip()
        if not entity_name or not birthdate_iso:
            continue

        passes = validate_birthdate(birthdate_iso)
        confidence = ConfidenceLevel.LLM_HIGH if passes else ConfidenceLevel.LLM_LOW
        canonical = _canonical_birthdate(birthdate_iso)

        fact, claim = _make_fact_and_claim(
            subject_id=_subject_id(entity_name),
            predicate="birthdate",
            canonical_value=canonical,
            value={"iso": birthdate_iso},
            source_doc_id=source_doc_id,
            valid_from=None,  # birthdate is invariant — no temporal interval
            valid_to=None,
            confidence=confidence,
            source_location=f"birthdate:{idx}",
        )
        facts.append(fact)
        claims.append(claim)

    return FactResult(facts=facts, claims=claims)


async def extract_employer_facts(
    *,
    content_md: str,
    source_doc_id: str,
    llm_func: LLMFunc,
    document_date: Optional[date] = None,
) -> FactResult:
    raw = await llm_func(_EMPLOYER_PROMPT.replace("{doc_text}", content_md or ""))
    items = parse_llm_json(raw)

    facts: list[Fact] = []
    claims: list[Claim] = []
    for idx, item in enumerate(items):
        employee_name = (item.get("employee_name") or "").strip()
        employer_name = (item.get("employer_name") or "").strip()
        if not employee_name or not employer_name:
            continue

        passes = validate_employer_name(employer_name)
        confidence = ConfidenceLevel.LLM_HIGH if passes else ConfidenceLevel.LLM_LOW
        canonical = _canonical_employer(employer_name)

        valid_from = _parse_optional_date(item.get("period_start_iso")) or document_date
        valid_to = _parse_optional_date(item.get("period_end_iso"))

        fact, claim = _make_fact_and_claim(
            subject_id=_subject_id(employee_name),
            predicate="employer",
            canonical_value=canonical,
            value={
                "employer": employer_name,
                "role": item.get("role"),
                "period_start_iso": item.get("period_start_iso"),
                "period_end_iso": item.get("period_end_iso"),
            },
            source_doc_id=source_doc_id,
            valid_from=valid_from,
            valid_to=valid_to,
            confidence=confidence,
            source_location=f"employer:{idx}",
        )
        facts.append(fact)
        claims.append(claim)

    return FactResult(facts=facts, claims=claims)

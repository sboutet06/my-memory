"""LLM-based document classifier — one call per doc at ingest time.

Assigns each ingested document 1–3 `doc_context` tags from a closed
vocabulary. Stored on `DocumentMetadata.doc_context`, user-overridable
via the source corrections overlay (`overrides.metadata.doc_context`).

Prompt is deliberately corpus-agnostic: vocabulary + content + filename,
no hints about which kinds to expect. New domains extend the vocabulary
(core table + pack contribution) without touching the prompt shape.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from lightrag.llm.openai import openai_complete_if_cache

from extraction.config import ExtractionConfig

logger = logging.getLogger(__name__)


# Closed vocabulary. Pack additions extend this list via `extend_doc_tags`.
DOC_CONTEXT_TAGS: list[str] = [
    "work",            # employment contracts, payslips, work correspondence
    "healthcare",      # medical records, prescriptions, tests, certificates
    "finance",         # bank statements, invoices, transaction records
    "property",        # real estate, deeds, rental contracts
    "vehicle",         # registration, insurance, purchase orders
    "identity",        # passport, ID card, birth certificate, driver's license
    "family",          # marriage, birth, family records (livret, lettre MV4)
    "legal",           # non-employment contracts, legal filings, notary
    "education",       # diplomas, transcripts, certifications, course reports
    "travel",          # tickets, itineraries, bookings, parking receipts
    "food",            # recipes, meal plans, nutrition guides
    "administrative",  # generic correspondence, forms, letters
    "other",           # fallback
]


_MAX_CONTENT_CHARS = 3000
_MAX_TAGS = 3


def _tag_set() -> set[str]:
    return set(DOC_CONTEXT_TAGS)


# --------------------------- response parsing ---------------------------


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _strip_fences(raw: str) -> str:
    m = _CODE_FENCE_RE.search(raw)
    return m.group(1) if m else raw


def parse_classifier_response(raw: str) -> tuple[list[str], str]:
    """Parse the LLM's JSON response into (tags, rationale).

    Robust to:
      - markdown code fences
      - extra prose surrounding the JSON
      - missing / malformed fields
      - unknown tags (dropped)
      - duplicate tags (deduped while preserving order)
      - uppercase tags (lowercased)

    Always returns a non-empty tag list — falls back to `["other"]`.
    """
    cleaned = _strip_fences(raw or "")
    cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find a {...} JSON object embedded in prose.
        brace = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if brace:
            try:
                data = json.loads(brace.group(0))
            except json.JSONDecodeError:
                return ["other"], "classifier response: invalid JSON"
        else:
            return ["other"], "classifier response: invalid JSON"

    if not isinstance(data, dict):
        return ["other"], "classifier response: not an object"

    raw_tags = data.get("tags") or []
    if not isinstance(raw_tags, list):
        raw_tags = []
    allowed = _tag_set()
    seen: set[str] = set()
    tags: list[str] = []
    for t in raw_tags:
        if not isinstance(t, str):
            continue
        canonical = t.strip().lower()
        if canonical in allowed and canonical not in seen:
            seen.add(canonical)
            tags.append(canonical)
    if not tags:
        tags = ["other"]
    tags = tags[:_MAX_TAGS]

    rationale = data.get("rationale")
    if not isinstance(rationale, str):
        rationale = ""
    return tags, rationale.strip()


# --------------------------- prompt assembly ----------------------------


def _vocab_list() -> str:
    return "\n".join(f"- {t}" for t in DOC_CONTEXT_TAGS)


def build_classifier_prompt(filename: str, content_md: str) -> str:
    body = (content_md or "").strip()[:_MAX_CONTENT_CHARS]
    return (
        "Classify the document into 1–3 tags from the closed vocabulary below, "
        "most relevant first.\n\n"
        "Vocabulary (use these exact strings):\n"
        f"{_vocab_list()}\n\n"
        f"Document filename: {filename}\n"
        "Document content (first 3000 characters):\n"
        "---\n"
        f"{body}\n"
        "---\n\n"
        "Respond with JSON only, no prose, no code fences:\n"
        '{"tags": ["tag1", "tag2"], "rationale": "one-sentence reason"}\n'
    )


# ------------------------------- runner ---------------------------------


async def classify_document(
    config: ExtractionConfig,
    *,
    filename: str,
    content_md: str,
) -> tuple[list[str], str]:
    """Call the LLM, parse, return (tags, rationale)."""
    api_key = config.require_api_key()
    prompt = build_classifier_prompt(filename, content_md)
    raw = await openai_complete_if_cache(
        config.llm_model,
        prompt,
        api_key=api_key,
        base_url=config.base_url,
        temperature=0.0,
    )
    return parse_classifier_response(raw or "")

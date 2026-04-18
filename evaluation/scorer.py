"""Pure scoring functions. No network, no LLM, deterministic."""
from __future__ import annotations

import unicodedata
from typing import Iterable


def _norm(s: str) -> str:
    return s.strip().lower()


def _nfc(s: str) -> str:
    """Normalize to NFC — macOS filesystems report filenames in NFD, while
    cases.json authors edit in NFC. Without this, `é` (U+00E9) vs `e\u0301`
    (U+0065 + U+0301) compare unequal even though they display identically.
    """
    return unicodedata.normalize("NFC", s)


def score_document_coverage(
    expected_doc_prefixes: Iterable[str],
    actual_doc_ids: Iterable[str],
) -> float:
    """Fraction of `expected_doc_prefixes` matched by any `actual_doc_ids`.

    Expected entries are treated as prefixes (so tests can use short
    `5905ca2e` for the full UUID). Empty `expected` → 1.0 (nothing to match).
    Prefix and candidate are both NFC-normalized so accented filenames
    from macOS (NFD) match prefixes authored in NFC.
    """
    expected = [_nfc(p) for p in expected_doc_prefixes if p]
    if not expected:
        return 1.0
    actual = [_nfc(a) for a in actual_doc_ids]
    hits = sum(1 for p in expected if any(a.startswith(p) for a in actual))
    return hits / len(expected)


def _substring_coverage(terms: Iterable[str], haystack: str) -> float:
    terms = [t for t in terms if t and t.strip()]
    if not terms:
        return 1.0
    hay = _norm(haystack)
    hits = sum(1 for t in terms if _norm(t) in hay)
    return hits / len(terms)


def score_entity_coverage(expected_entities: Iterable[str], answer: str) -> float:
    """Case-insensitive substring match. 1.0 when all expected appear."""
    return _substring_coverage(expected_entities, answer)


def score_fact_coverage(expected_facts: Iterable[str], answer: str) -> float:
    """Case-insensitive substring match. 1.0 when all expected appear."""
    return _substring_coverage(expected_facts, answer)


def count_forbidden(forbidden: Iterable[str], answer: str) -> int:
    """Number of forbidden terms that appear in the answer. Term-level count."""
    hay = _norm(answer)
    return sum(1 for t in forbidden if t and _norm(t) in hay)

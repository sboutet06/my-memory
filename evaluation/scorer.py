"""Pure scoring functions. No network, no LLM, deterministic.

Matching semantics (entity/fact/forbidden):
- Accent-insensitive: NFKD decomposition strips combining marks, so
  `Zoé` matches `Zoe` and `ingénieur` matches `ingenieur`. This avoids
  brittle false-negatives on common French-accent drift between source
  text, LLM paraphrase, and eval fixtures.
- Case-insensitive: lowercase both sides.
- OR alternatives: an expected entry containing `|` is split and each
  alternative is tested in turn — any match counts the entry as
  satisfied. Addresses synonym drift (`ordonnance|prescription`).
"""
from __future__ import annotations

import unicodedata
from typing import Iterable


def _fold(s: str) -> str:
    """NFKD decompose → strip combining marks → lowercase → trim.

    `é` (U+00E9) → `e` + U+0301 → `e`. Same output for NFC and NFD
    inputs, makes matching immune to OS filesystem normalization,
    accent drift, and case.
    """
    decomposed = unicodedata.normalize("NFKD", s)
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return no_marks.strip().lower()


# Kept for callers that need simple case-insensitive comparison without
# accent folding; scoring functions use `_fold` internally.
def _norm(s: str) -> str:
    return s.strip().lower()


def _nfc(s: str) -> str:
    """Normalize to NFC — macOS filesystems report filenames in NFD, while
    cases.json authors edit in NFC. Without this, `é` (U+00E9) vs `e\u0301`
    (U+0065 + U+0301) compare unequal even though they display identically.
    """
    return unicodedata.normalize("NFC", s)


def _alternatives(raw: str) -> list[str]:
    """Split on `|` to support OR alternatives in expected entries.

    Empty alternatives dropped. `"ordonnance|prescription"` →
    ["ordonnance", "prescription"]; `"single"` → ["single"].
    """
    return [p.strip() for p in raw.split("|") if p.strip()]


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
    hay = _fold(haystack)
    # Each entry counts if ANY of its `|`-separated alternatives appears.
    hits = 0
    for entry in terms:
        alts = _alternatives(entry) or [entry]
        if any(_fold(alt) in hay for alt in alts):
            hits += 1
    return hits / len(terms)


def score_entity_coverage(expected_entities: Iterable[str], answer: str) -> float:
    """Accent+case-insensitive substring match with `|` OR alternatives."""
    return _substring_coverage(expected_entities, answer)


def score_fact_coverage(expected_facts: Iterable[str], answer: str) -> float:
    """Accent+case-insensitive substring match with `|` OR alternatives."""
    return _substring_coverage(expected_facts, answer)


def score_fact_provenance_coverage(
    expected_provenance: Iterable[str], answer: str,
) -> float:
    """Fraction of expected provenance strings present in the answer.

    Same accent+case-insensitive substring matching with `|` OR
    alternatives as `score_fact_coverage`. Empty expected → 1.0.
    """
    return _substring_coverage(expected_provenance, answer)


def score_temporal_accuracy(
    expected_temporal: Iterable[str], answer: str,
) -> float:
    """Fraction of expected temporal facts present in the answer.

    Used for as_of and supersession-aware queries — the answer should
    reference values valid at the date in question (or surface the
    relevant timeline). Same accent+case-insensitive substring matching
    with `|` OR alternatives. Empty expected → 1.0.
    """
    return _substring_coverage(expected_temporal, answer)


def score_conflict_detection_coverage(
    expected_conflicts: Iterable[str], answer: str,
) -> float:
    """Fraction of expected conflict indicators present in the answer.

    An answer passes if it surfaces both/all conflicting values — meaning
    the user can see the disagreement rather than having it silently resolved.
    Same accent+case-insensitive matching with `|` OR alternatives.
    Empty expected → 1.0 (no conflict expected for this case).
    """
    return _substring_coverage(expected_conflicts, answer)


def score_abstention_accuracy(expects_abstention: bool, answer: str) -> float:
    """1.0 iff the answer correctly abstains (or correctly answers).

    Phase 8b.6 — premortem F6 / charter §3.8c. The accountability product
    must be allowed to say "I do not have sufficient evidence" rather
    than confabulate. This metric scores whether the query answerer
    abstains on cases where the corpus does not warrant a confident
    answer.

    Semantics:
    - `expects_abstention=False`: this case does not measure abstention
      → 1.0 (skip from this metric's perspective; other metrics judge).
    - `expects_abstention=True`: the corpus does NOT contain sufficient
      evidence. 1.0 if the answer surfaces an abstention marker, else
      0.0. Markers cover both French ("insuffisant", "ne dispose pas",
      "n'apparaît pas", "absent du corpus", "aucune information") and
      English fallbacks ("insufficient evidence", "do not have
      sufficient", "no information", "cannot determine").

    Forbidden-style anti-marker (for future extension): if the answer
    confidently asserts a value AND we expected abstention, that's a
    confabulation. v0.5 scores binary on the marker only; calibration
    against confabulation is V1 work.
    """
    if not expects_abstention:
        return 1.0

    folded = _fold(answer)
    # Permissive marker set: any single phrase here = abstention.
    # FR + EN; folded comparison strips accents and lowercases.
    markers = (
        # French
        "insuffisant", "insuffisamment", "pas suffisamment",
        "ne dispose pas", "ne contient pas", "ne contient aucun",
        "n'apparait pas", "n apparait pas",
        "absent du corpus", "aucune information",
        "non disponible", "impossible de determiner",
        # English
        "insufficient", "no information", "cannot determine",
        "not enough", "do not have sufficient",
        "does not contain sufficient", "does not contain enough",
        "lacks sufficient",
    )
    for marker in markers:
        if _fold(marker) in folded:
            return 1.0
    return 0.0


def count_forbidden(forbidden: Iterable[str], answer: str) -> int:
    """Number of forbidden entries present in the answer. Term-level count.

    Entries may use `|` for OR — if any alternative is present, the entry
    counts as one violation.
    """
    hay = _fold(answer)
    violations = 0
    for entry in forbidden:
        if not entry:
            continue
        alts = _alternatives(entry) or [entry]
        if any(_fold(alt) in hay for alt in alts):
            violations += 1
    return violations

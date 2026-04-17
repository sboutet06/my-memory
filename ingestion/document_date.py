"""Heuristic document-date detection. Pure, offline, no LLM.

Strategy, first match wins:
1. Date in the body, anchored to an issue-keyword (`émise le`, `date`, …).
2. Any plausible date in the body's first window.
3. A date-like segment embedded in the filename (`YYYYMMDD`, `YYYY-MM-DD`).

Returns `None` when nothing plausible is found — better no date than a
wrong one. Temporal reasoning downstream must treat `None` as "unknown".
"""
from __future__ import annotations

import re
from datetime import date

# Scan only a small header window of the body — document dates live up top
# (facture headers, form metadata, letter salutations). Anything deeper is
# noise for our purposes.
_BODY_SCAN_CHARS = 3000

_MIN_YEAR, _MAX_YEAR = 1900, 2100

# Issue-date keywords — generic across languages, not French-specific.
# Deliberately excludes bare `le` (too greedy: matches "né le …" birthdates)
# and bare `on` (too greedy).
_KEYWORD_PATTERN = re.compile(
    r"(?:"
    r"émise?\s+le|emise?\s+le"
    r"|date\s*[:\-]"
    r"|dated"
    r"|signé\s+le|signe\s+le"
    r"|rédigé\s+le|redige\s+le"
    r"|issued(?:\s+on)?"
    r"|generated\s+on"
    r"|fait\s+le"
    r")",
    re.IGNORECASE,
)

# Contexts that disqualify a date from being the document-issue date.
# Covers birthdates, validity windows, expiry — things commonly mined
# by noise regexes. Matched anywhere in a short lookback window, not
# anchored: we accept that "né" appearing within ~15 chars of a date is
# almost always a birthdate reference.
_DISQUALIFYING_PRIOR = re.compile(
    r"\b(?:n[ée]e?|naissance|born|depuis|jusqu[' ]?au?|expir|valid\s+(?:from|until)|birth)\b",
    re.IGNORECASE,
)

_LOOKBACK_CHARS = 25


def _is_disqualified_at(window: str, position: int) -> bool:
    """Does the ~25 chars before `position` contain a disqualifying phrase?"""
    lookback = window[max(0, position - _LOOKBACK_CHARS): position]
    return bool(_DISQUALIFYING_PRIOR.search(lookback))

# Date regexes — broad set of common separators.
# Order here matters only for tie-breaking inside a single span (ISO first so
# "2020-03-15" doesn't read as "20-03-15").
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # ISO: YYYY-MM-DD
    re.compile(r"(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})"),
    # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    re.compile(r"(?P<d>\d{1,2})[/.\-](?P<m>\d{1,2})[/.\-](?P<y>\d{4})"),
    # YYYY/MM/DD
    re.compile(r"(?P<y>\d{4})/(?P<m>\d{1,2})/(?P<d>\d{1,2})"),
)

# Compact filename date: YYYYMMDD or YYYY-MM-DD.
_FILENAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})"),
    re.compile(r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})"),
)


def _coerce(year: int, month: int, day: int) -> date | None:
    if not (_MIN_YEAR <= year <= _MAX_YEAR):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _first_date_in(window: str, *, base_offset: int = 0) -> date | None:
    """Return the earliest-positioned valid, non-disqualified date in `window`.

    `base_offset` is the absolute position of `window[0]` in the original
    text, used so the disqualifying-context lookback can see a few chars
    that fell just outside this sub-window.
    """
    best: tuple[int, date] | None = None
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(window):
            candidate = _coerce(int(m.group("y")), int(m.group("m")), int(m.group("d")))
            if candidate is None:
                continue
            # Disqualify birthdates and validity windows.
            if _is_disqualified_at(window, m.start()):
                continue
            if best is None or m.start() < best[0]:
                best = (m.start(), candidate)
    return best[1] if best else None


def _keyword_anchored_date(window: str) -> date | None:
    """Find a date within a short span after any issue-keyword."""
    for km in _KEYWORD_PATTERN.finditer(window):
        # Search up to ~40 chars past the keyword — enough to catch
        # `Émise le 12/06/2015` or `Date : 2021-02-28` without drifting.
        span = window[km.end(): km.end() + 40]
        found = _first_date_in(span)
        if found is not None:
            return found
    return None


def _filename_date(filename: str) -> date | None:
    stem = filename
    for pat in _FILENAME_PATTERNS:
        m = pat.search(stem)
        if not m:
            continue
        candidate = _coerce(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        if candidate is not None:
            return candidate
    return None


def detect_document_date(content_text: str, filename: str) -> date | None:
    """Best-effort document date. Returns None if uncertain."""
    window = (content_text or "")[:_BODY_SCAN_CHARS]
    return (
        _keyword_anchored_date(window)
        or _first_date_in(window)
        or _filename_date(filename or "")
    )

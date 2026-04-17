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

# Scan both ends of the body. Document dates live in headers (facture,
# form metadata, letter salutations) OR in footers (legal docs signed
# with "Fait à X le Y"). The middle is almost always body content with
# event-dates that aren't the document's own date.
_HEAD_SCAN_CHARS = 3000
_TAIL_SCAN_CHARS = 3000

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
    r"|fait\s+(?:[aà]|le)"  # "fait le X" or "FAIT à <lieu> Le X"
    r")",
    re.IGNORECASE,
)

# Contexts that disqualify a date from being the document-issue date.
# Covers birthdates, validity windows, expiry — things commonly mined
# by noise regexes. Matched anywhere in a short lookback window, not
# anchored: we accept that "né" appearing within ~15 chars of a date is
# almost always a birthdate reference.
_DISQUALIFYING_PRIOR = re.compile(
    r"\b(?:n[ée]e?|naissance|born|depuis|jusqu[' ]?au?|expir|valid\s+(?:from|until)|"
    r"birth|mari[ée]s?|married)\b",
    re.IGNORECASE,
)

_LOOKBACK_CHARS = 40


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

# Textual French dates — "22 avril 2016", "5 août 2008". Generic month list
# (accented + unaccented). Used as a fallback alongside the numeric formats.
_FR_MONTHS: dict[str, int] = {
    "janvier": 1,
    "février": 2, "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8, "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12, "decembre": 12,
}
_TEXTUAL_DATE_PATTERN = re.compile(
    r"(?P<d>\d{1,2})\s+(?P<mname>"
    + "|".join(sorted(_FR_MONTHS.keys(), key=len, reverse=True))
    + r")\s+(?P<y>\d{4})",
    re.IGNORECASE,
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


def _iter_candidate_dates(window: str) -> list[tuple[int, date]]:
    """Yield `(position, date)` for every valid, non-disqualified date match.

    Scans numeric formats AND French textual dates (`22 avril 2016`).
    Applies the birthdate/validity-window filter.
    """
    out: list[tuple[int, date]] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(window):
            candidate = _coerce(int(m.group("y")), int(m.group("m")), int(m.group("d")))
            if candidate is None:
                continue
            if _is_disqualified_at(window, m.start()):
                continue
            out.append((m.start(), candidate))
    for m in _TEXTUAL_DATE_PATTERN.finditer(window):
        month = _FR_MONTHS.get(m.group("mname").lower())
        if month is None:
            continue
        candidate = _coerce(int(m.group("y")), month, int(m.group("d")))
        if candidate is None:
            continue
        if _is_disqualified_at(window, m.start()):
            continue
        out.append((m.start(), candidate))
    return out


def _earliest_date_in(window: str) -> date | None:
    """Earliest-positioned valid date. Used inside a short keyword span."""
    candidates = _iter_candidate_dates(window)
    if not candidates:
        return None
    return min(candidates, key=lambda t: t[0])[1]


def _latest_date_value_in(window: str) -> date | None:
    """Most-recent-by-value date. Heuristic for undated docs: the latest
    date mentioned in the header is usually the issue date."""
    candidates = _iter_candidate_dates(window)
    if not candidates:
        return None
    return max(candidates, key=lambda t: t[1])[1]


def _keyword_anchored_date(window: str) -> date | None:
    """Find a date within a short span after any issue-keyword.

    Span is 60 chars — enough to cover `FAIT à CHATEAUNEUF Le 13 mai 2016`
    where the location sits between the keyword and the date.
    """
    for km in _KEYWORD_PATTERN.finditer(window):
        span = window[km.end(): km.end() + 60]
        found = _earliest_date_in(span)
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


def _head_and_tail(text: str) -> str:
    """Concatenate the head + tail of `text`. Legal docs sign at the bottom."""
    if len(text) <= _HEAD_SCAN_CHARS + _TAIL_SCAN_CHARS:
        return text
    head = text[:_HEAD_SCAN_CHARS]
    tail = text[-_TAIL_SCAN_CHARS:]
    # Separate with a newline so a date at the head boundary doesn't glue
    # to a date at the tail boundary.
    return head + "\n" + tail


def detect_document_date(content_text: str, filename: str) -> date | None:
    """Best-effort document date. Returns None if uncertain.

    Priority:
      1. Date after an issue-keyword (`émise le`, `date:`, `signé le`,
         `fait à X le`, …) anywhere in the head OR tail window.
      2. Filename-embedded date (`YYYYMMDD`, `YYYY-MM-DD`).
      3. Most-recent date mentioned in the scan window. Past-event dates
         in the body are typically older than the doc's own date.
    """
    window = _head_and_tail(content_text or "")
    return (
        _keyword_anchored_date(window)
        or _filename_date(filename or "")
        or _latest_date_value_in(window)
    )

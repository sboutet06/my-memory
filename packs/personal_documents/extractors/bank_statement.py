"""Regex-based extractor for French `RELEVE DE COMPTE` bank statements.

Parses the transaction table in the Docling markdown of a statement PDF
into a list of `Transaction` records. Deterministic — no LLM calls.

Scoped to the format produced by the dogfood BNP-style statements; other
bank formats will need their own extractor (or a more tolerant one).
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from packs.personal_documents.schemas.transaction import Transaction

# --------------------------- low-level parsers ---------------------------

_FR_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    "decembre": 12,
}

_PERIOD_RE = re.compile(
    r"du\s+(\d{1,2})\s+([A-Za-zéû]+)\s+(\d{4})\s+au\s+(\d{1,2})\s+([A-Za-zéû]+)\s+(\d{4})",
    re.IGNORECASE,
)

_RIB_RE = re.compile(r"RIB\s*:\s*([0-9 ]+?)(?=\s*$|\s+IBAN|\n)", re.MULTILINE)

# Skip non-transaction rows.
_SKIP_PREFIXES = ("SOLDE ", "TOTAL DES OPERATIONS")


def parse_amount_fr(raw: str) -> Optional[Decimal]:
    """Parse a French-formatted number: `1 209,10` → Decimal('1209.10')."""
    s = raw.strip().replace("\u00a0", " ")
    if not s:
        return None
    s = s.replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_day_month(raw: str, period: tuple[date, date]) -> Optional[date]:
    """Resolve `DD.MM` to a full date using the statement period bounds.

    If start/end fall in the same year, straightforward. If the period
    crosses Dec→Jan, pick the year that contains this month.
    """
    s = raw.strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", s)
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    start, end = period
    if start.year == end.year:
        return date(start.year, month, day)
    # Cross-year: month matching start.year wins if <= start's month range, else end.year.
    if month >= start.month:
        return date(start.year, month, day)
    return date(end.year, month, day)


def parse_statement_period(text: str) -> Optional[tuple[date, date]]:
    """Find `du DD mois YYYY au DD mois YYYY` and return the two bounds."""
    m = _PERIOD_RE.search(text)
    if not m:
        return None
    try:
        d1 = date(int(m.group(3)), _FR_MONTHS[m.group(2).lower()], int(m.group(1)))
        d2 = date(int(m.group(6)), _FR_MONTHS[m.group(5).lower()], int(m.group(4)))
    except (KeyError, ValueError):
        return None
    return d1, d2


def parse_rib(text: str) -> Optional[str]:
    m = _RIB_RE.search(text)
    if not m:
        return None
    # Collapse internal whitespace and trim.
    return " ".join(m.group(1).split())


# ----------------------------- main extractor ----------------------------


def _split_row(row: str) -> list[str]:
    # Leading/trailing `|` produce empty strings; drop them.
    cells = [c.strip() for c in row.split("|")]
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def _is_separator(row: str) -> bool:
    return all(
        re.fullmatch(r":?-+:?", c) is not None
        for c in _split_row(row) if c
    )


def _is_header(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    return ("date" in joined and "débit" in joined.replace("é", "é")
            or ("date" in joined and "débit" in joined)
            or ("ate" in joined and "ébit" in joined))  # tolerate Docling's broken spacing


def _skip_row(cells: list[str]) -> bool:
    desc = cells[1] if len(cells) > 1 else ""
    stripped = desc.strip().upper()
    return any(stripped.startswith(p) for p in _SKIP_PREFIXES)


def extract_transactions(markdown: str, *, source_doc_id: str) -> list[Transaction]:
    """Parse the first transaction table in `markdown` into Transaction records.

    Returns `[]` on any of: missing statement period, no table found,
    malformed rows. Individual unparseable rows are skipped with the
    others preserved.
    """
    period = parse_statement_period(markdown)
    if period is None:
        return []
    rib = parse_rib(markdown)

    transactions: list[Transaction] = []
    in_table = False
    seen_header = False
    for line in markdown.splitlines():
        if not line.lstrip().startswith("|"):
            in_table = False
            seen_header = False
            continue
        if _is_separator(line):
            continue
        cells = _split_row(line)
        if not seen_header:
            if _is_header(cells):
                seen_header = True
                in_table = True
            continue
        if not in_table or len(cells) < 5:
            continue
        if _skip_row(cells):
            continue

        d_raw, desc, vd_raw, debit_raw, credit_raw = cells[:5]
        d = parse_day_month(d_raw, period)
        vd = parse_day_month(vd_raw, period) or d
        if d is None or not desc:
            continue
        debit = parse_amount_fr(debit_raw)
        credit = parse_amount_fr(credit_raw)
        if debit is None and credit is None:
            continue
        try:
            transactions.append(Transaction(
                date=d, value_date=vd, description=desc,
                debit=debit, credit=credit,
                account_rib=rib, source_doc_id=source_doc_id,
            ))
        except Exception:
            # A single malformed row must not abort the whole extraction.
            continue
    return transactions

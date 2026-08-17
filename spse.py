"""spse.py — scrape procurement data from https://spse.inaproc.id.

Run with no arguments for a Tkinter GUI; run with arguments for a headless
CLI suitable for automation. See SPSE_SCRAPER.md for the site contract and
docs/plans/2026-08-17-spse-scraper-gui-design.md for the design rationale.
"""

from __future__ import annotations

import re
import sys
from datetime import date


if sys.platform == "win32":
    # The Windows console defaults to cp1252 and raises UnicodeEncodeError on
    # Indonesian package names; force UTF-8 on both streams. reconfigure() is
    # used rather than wrapping sys.stdout.buffer in a new TextIOWrapper: a
    # fresh wrapper takes ownership of a buffer it did not create and closes it
    # when garbage collected, which breaks any host that has already replaced
    # the streams (pytest's capture, IDLE, a GUI redirect).
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            try:
                _reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    del _stream, _reconfigure

_BULAN = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11,
    "desember": 12,
}

_WS_RE = re.compile(r"\s+")
_TANGGAL_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$")
# 'Rp. 787.406.000,00' or a bare '1.000.000,00'. The 'Rp' prefix is optional:
# the winner sub-tables (Harga Kontrak, Nilai PDN, Nilai UMK) are empty in
# every saved fixture, so requiring the prefix could silently blank real
# contract prices. Anything else -- 'APBN 2026', 'Peserta 3', 'Lumsum' -- must
# not be mistaken for money.
_RUPIAH_RE = re.compile(r"^(?:Rp\.?\s*)?([\d.,]+)$", re.IGNORECASE)


def clean_text(value: str | None) -> str:
    """Collapse runs of whitespace to one space and strip the ends.

    None and every other falsy input become "", so callers can treat a missing
    cell and an empty cell alike.
    """
    if not value:
        return ""
    # \s already covers \xa0, but SPSE values are littered with literal &nbsp;
    # so the replace stays as documentation of the intent.
    return _WS_RE.sub(" ", value.replace("\xa0", " ")).strip()


def parse_rupiah(value: str | None) -> float | None:
    """'Rp. 787.406.000,00' -> 787406000.0; None when not a currency string.

    The 'Rp' prefix is optional, so a bare '1.000.000,00' also parses; see
    _RUPIAH_RE for why. Anything else -- 'APBN 2026', 'Lumsum', '-' -- is None.
    """
    match = _RUPIAH_RE.match(clean_text(value))
    if not match:
        return None
    digits = match.group(1)
    if not any(char.isdigit() for char in digits):
        return None
    # Indonesian format: '.' groups thousands, ',' is the decimal separator.
    digits = digits.replace(".", "").replace(",", ".")
    try:
        return float(digits)
    except ValueError:
        return None


def parse_tanggal(value: str | None) -> str | None:
    """'11 Agustus 2026' -> '2026-08-11'; None when not a real date.

    Impossible dates such as '31 Februari 2026' are rejected rather than
    formatted: a blank is recoverable downstream, a fake ISO date is not.
    """
    match = _TANGGAL_RE.match(clean_text(value))
    if not match:
        return None
    day, month_name, year = match.groups()
    month = _BULAN.get(month_name.lower())
    if not month:
        return None
    try:
        return date(int(year), month, int(day)).isoformat()
    except ValueError:
        return None

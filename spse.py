"""spse.py — scrape procurement data from https://spse.inaproc.id.

Run with no arguments for a Tkinter GUI; run with arguments for a headless
CLI suitable for automation. See SPSE_SCRAPER.md for the site contract and
docs/plans/2026-08-17-spse-scraper-gui-design.md for the design rationale.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from html.parser import HTMLParser
from typing import TypedDict


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


class Tab(TypedDict):
    """One entry of a detail page's tab bar.

    A TypedDict rather than a dataclass or NamedTuple: later stages may enrich
    these dicts with extra keys, and a typo like tab["urls"] is then a type
    error at author time instead of a KeyError inside a worker thread.
    """

    url: str
    label: str
    active: bool


class _TabParser(HTMLParser):
    """Collect the `a.nav-link` entries of the detail-page tab bar.

    The class attribute is matched token-wise, not by substring: SPSE writes it
    with irregular internal whitespace ('nav-link  active ') and 'active' is
    absent on inactive tabs. Only absolute http(s) hrefs are accepted, so
    callers may fetch tab['url'] and derive a filename from it unconditionally.

    An instance is single-use: reset() does not clear `tabs`, so feeding a
    second document would append to the first one's results.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabs: list[Tab] = []
        self._current: Tab | None = None

    def _flush(self) -> None:
        """Finish the open tab, if any, and append it to `tabs`."""
        if self._current is None:
            return
        self._current["label"] = clean_text(self._current["label"])
        self.tabs.append(self._current)
        self._current = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr = dict(attrs)
        # An attribute present but valueless parses as None, hence the `or ""`.
        classes = (attr.get("class") or "").split()
        href = attr.get("href") or ""
        # Reject relative and fragment hrefs ('#tab-jadwal'): the caller turns
        # this URL into both a request and a filename, and '#tab-jadwal' would
        # yield a malformed request plus the filename 'index.html' for every
        # such tab. Dropping an unfetchable tab beats emitting a colliding one.
        if "nav-link" not in classes or not href.startswith(("http://", "https://")):
            return
        # Flush rather than overwrite: markup missing a '</a>' would otherwise
        # discard the tab already open, silently costing a whole tab download.
        self._flush()
        self._current = {"url": href, "active": "active" in classes, "label": ""}

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["label"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._flush()


def find_tabs(html_text: str) -> list[Tab]:
    """Return this package's real tabs: [{'url', 'label', 'active'}, ...].

    SPSE renders absolute hrefs here, and the set varies per package (an
    unawarded tender has no evaluasi tabs), so this is the authority on which
    tabs to fetch rather than a hardcoded table. Every returned 'url' is an
    absolute http(s) URL; anything else in the markup is skipped.

    An empty list always means "this is not a detail page" -- the fetch failed,
    returned an error page, or hit a login redirect. It never means "a package
    with no tabs": every real detail page carries at least a Pengumuman tab.
    Callers must treat [] as failure, not as an empty success.
    """
    parser = _TabParser()
    parser.feed(html_text)
    return parser.tabs

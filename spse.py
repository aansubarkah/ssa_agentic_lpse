"""spse.py — scrape procurement data from https://spse.inaproc.id.

Run with no arguments for a Tkinter GUI; run with arguments for a headless
CLI suitable for automation. See SPSE_SCRAPER.md for the site contract and
docs/plans/2026-08-17-spse-scraper-gui-design.md for the design rationale.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse
from urllib.parse import urlparse as _urlparse

import requests


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
_TAG_RE = re.compile(r"<[^>]+>")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


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


def strip_tags(value: str) -> str:
    """DataTables cells sometimes contain anchors; keep only their text."""
    return clean_text(_TAG_RE.sub(" ", value or ""))


def extract_ids(rows: list, kategori: str) -> list[str]:
    """Pull the package id out of each list row."""
    index = CATEGORIES[kategori]["id_index"]
    ids: list[str] = []
    for row in rows:
        if len(row) <= index:
            continue
        value = strip_tags(str(row[index]))
        if value:
            ids.append(value)
    return ids


def filter_rows_by_year(rows: list, tahun: int) -> list:
    """Keep rows mentioning the given year; keep rows with no year at all.

    Only needed for swakelola and darurat, whose endpoints ignore tahun. Rows
    without any recognisable year are kept, because dropping real data is worse
    than exporting a little extra.
    """
    wanted = str(tahun)
    kept = []
    for row in rows:
        text = " ".join(strip_tags(str(cell)) for cell in row)
        years = _YEAR_RE.findall(text)
        if not years:
            kept.append(row)
        elif wanted in text:
            kept.append(row)
    return kept


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


class _DetailParser(HTMLParser):
    """Extract label/value fields and nested sub-tables from a detail page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, str] = {}
        self.tables: list[dict] = []
        self._in_content = False
        self._content_depth = 0        # div nesting inside div.content
        self._table_depth = 0
        # One cell list per open table, not one shared list. A sub-table sits
        # inside a <td colspan> of the outer table, so its <tr> tags fire while
        # the outer row is still open; resetting a shared list there wiped the
        # outer row's already-closed label cell ('Rencana Umum Pengadaan',
        # 'Syarat Kualifikasi') and cost those fields entirely.
        self._cells_stack: list[list[dict]] = []
        self._cell: dict | None = None
        # A cell still open when a nested <table> starts is parked here and
        # restored at </table>. Without parking, the nested <th>/<td> tags
        # overwrite self._cell and the enclosing cell's text is dropped.
        self._parked_cells: list[dict] = []
        self._rows_stack: list[list] = []   # one row list per open table

    # -- div tracking ----------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list) -> None:
        attr = dict(attrs)
        if tag == "div":
            if self._in_content:
                self._content_depth += 1
            elif "content" in (attr.get("class") or "").split():
                self._in_content = True
                self._content_depth = 1
            return
        if not self._in_content:
            return
        if tag == "table":
            self._table_depth += 1
            self._rows_stack.append([])
            self._cells_stack.append([])
            if self._cell is not None:
                self._parked_cells.append(self._cell)
                self._cell = None
        elif tag == "tr":
            # Reset only the innermost table's row; outer rows stay intact.
            if self._cells_stack:
                self._cells_stack[-1] = []
        elif tag in ("th", "td"):
            self._cell = {
                "tag": tag,
                "classes": (attr.get("class") or "").split(),
                "text": "",
                "links": [],
                "depth": self._table_depth,
            }
        elif tag == "a" and self._cell is not None and attr.get("href"):
            self._cell["links"].append(attr["href"])

    def handle_data(self, data: str) -> None:
        # Only accumulate text belonging to the innermost open table, so a
        # nested table's contents do not pollute the enclosing cell's value.
        # While a nested table is open the enclosing cell is parked (None),
        # which is what keeps sub-table text out of the field's value.
        if self._cell is not None and self._cell["depth"] == self._table_depth:
            self._cell["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_content:
            self._content_depth -= 1
            if self._content_depth <= 0:
                self._in_content = False
            return
        if not self._in_content:
            return
        if tag in ("th", "td"):
            if self._cell is not None:
                self._cell["text"] = clean_text(self._cell["text"])
                # A cell closes in the table it was opened in, which is not
                # necessarily the innermost one: the <td> wrapping a sub-table
                # ends only after the sub-table's </table> has fired.
                depth = self._cell["depth"] - 1
                if 0 <= depth < len(self._cells_stack):
                    self._cells_stack[depth].append(self._cell)
                self._cell = None
        elif tag == "tr":
            self._finish_row()
        elif tag == "table":
            self._finish_table()

    # -- row / table classification --------------------------------------
    def _finish_row(self) -> None:
        if not self._cells_stack:
            return
        cells = [c for c in self._cells_stack[-1] if c["depth"] == self._table_depth]
        self._cells_stack[-1] = []
        if not cells:
            return
        first = cells[0]
        if first["tag"] == "th" and "bgwarning" in first["classes"]:
            self._emit_fields(cells)
            return
        if self._rows_stack:
            self._rows_stack[-1].append(
                {"tags": [c["tag"] for c in cells],
                 "values": [c["text"] for c in cells]}
            )

    def _emit_fields(self, cells: list[dict]) -> None:
        # Most field rows are one label followed by its value cells, but the
        # non-tender pengumuman page packs 'Nilai Pagu Paket' and 'Nilai HPS
        # Paket' into a single <tr> (th, td, th, td). The row is therefore
        # split at every bgwarning cell; each label owns the plain cells up
        # to the next label (or the end of the row).
        starts = [i for i, c in enumerate(cells)
                  if c["tag"] == "th" and "bgwarning" in c["classes"]]
        for position, start in enumerate(starts):
            end = starts[position + 1] if position + 1 < len(starts) else len(cells)
            value_cells = cells[start + 1:end]
            label = cells[start]["text"]
            value = " ".join(c["text"] for c in value_cells if c["text"]).strip()
            links = [href for c in value_cells for href in c["links"]]
            self.fields[label] = clean_text(value)
            if links:
                self.fields.setdefault(f"{label} [url]", links[0])

    def _finish_table(self) -> None:
        rows = self._rows_stack.pop() if self._rows_stack else []
        if self._cells_stack:
            self._cells_stack.pop()
        if self._parked_cells:
            # Restore the cell this table was nested inside, if any, so text
            # after the sub-table still lands in the enclosing value.
            self._cell = self._parked_cells.pop()
        self._table_depth = max(0, self._table_depth - 1)
        if not rows:
            return
        header: list[str] = []
        data_rows: list[list[str]] = []
        for row in rows:
            if all(tag == "th" for tag in row["tags"]) and not header:
                header = row["values"]
            else:
                data_rows.append(row["values"])
        self.tables.append({"header": header, "rows": data_rows})


# Header signatures that identify a sub-table, checked in order.
TABLE_SIGNATURES = [
    ("pemenang", "Nama Pemenang"),
    ("peserta", "Nama Peserta"),
    ("rup", "Kode RUP"),
    ("realisasi", "Jenis Realisasi"),
    ("kualifikasi", "Jenis Izin"),
]


def name_tables(tables: list[dict]) -> dict[str, dict]:
    """Key sub-tables by what they contain rather than by position.

    Position is unreliable: the number and order of sub-tables differs per
    category and per tab. Unrecognised tables are kept as table1, table2, ...
    so nothing is silently lost.
    """
    named: dict[str, dict] = {}
    unknown = 0
    for table in tables:
        header = table["header"]
        key = None
        for candidate, marker in TABLE_SIGNATURES:
            if any(marker in column for column in header):
                key = candidate
                break
        if key is None:
            unknown += 1
            key = f"table{unknown}"
        named.setdefault(key, table)
    return named


def parse_detail(html_text: str) -> dict:
    """Parse one SPSE detail page.

    Returns {'fields': {label: value}, 'tables': [...],
    'named_tables': {key: table}, 'tabs': [...]}.
    One parser serves all five categories because every detail page shares
    the same markup contract; see SPSE_SCRAPER.md.
    """
    parser = _DetailParser()
    parser.feed(html_text)
    tables = parser.tables
    return {
        "fields": parser.fields,
        "tables": tables,
        "named_tables": name_tables(tables),
        "tabs": find_tabs(html_text),
    }


DELAY_S = 0.6           # between list pages; tuned to avoid rate limiting
PAGE_SIZE = 10000       # DataTables rows per request
MAX_RETRIES = 3
MIN_FILE_SIZE = 200     # bytes; anything smaller is an error page, re-fetch it
DEFAULT_WORKERS = 8

CATEGORIES: dict[str, dict] = {
    "tender": {
        "label": "Tender",
        "listing": "lelang",
        "endpoint": "dt/lelang",
        "query": "?rekanan=&tahun={tahun}&instansiId=",
        "accepts_tahun": True,
        "columns": 16,
        "order_column": 5,
        "entry_tab": "/lelang/{id}/pengumumanlelang",
        "id_index": 0,
    },
    "nontender": {
        "label": "Non Tender",
        "listing": "nontender",
        "endpoint": "dt/pl",
        "query": "?tahun={tahun}",
        "accepts_tahun": True,
        "columns": 12,
        "order_column": 5,
        "entry_tab": "/nontender/{id}/pengumumanpl",
        "id_index": 0,
    },
    "pencatatan": {
        "label": "Pencatatan Non Tender",
        "listing": "pencatatan",
        "endpoint": "dt/nonspk",
        "query": "?rekanan=&tahun={tahun}&instansiId=",
        "accepts_tahun": True,
        "columns": 9,
        "order_column": 0,
        "entry_tab": "/pencatatan/pengumumannonspk?id={id}",
        "id_index": 0,
    },
    "swakelola": {
        "label": "Pencatatan Swakelola",
        "listing": "swakelola",
        "endpoint": "dt/swakelola",
        "query": "",
        "accepts_tahun": False,
        "columns": 5,
        "order_column": 0,
        "entry_tab": "/swakelola/{id}/pengumuman",
        "id_index": 0,
    },
    "darurat": {
        "label": "Pencatatan Pengadaan Darurat",
        "listing": "darurat",
        "endpoint": "dt/darurat-list",
        "query": "",
        "accepts_tahun": False,
        "columns": 5,
        "order_column": 0,
        "entry_tab": "/darurat/pengumumandarurat?id={id}",
        "id_index": 0,
    },
}


def build_dt_body(token: str, kategori: str, start: int, length: int) -> str:
    """Build the DataTables server-side POST body for one page of results."""
    cfg = CATEGORIES[kategori]
    parts: list[str] = []

    def add(key: str, value: str = "") -> None:
        parts.append(f"{key}={value}")

    add("draw", "1")
    for index in range(cfg["columns"]):
        add(f"columns[{index}][data]", str(index))
        add(f"columns[{index}][name]")
        add(f"columns[{index}][searchable]", "true")
        add(f"columns[{index}][orderable]", "true")
        add(f"columns[{index}][search][value]")
        add(f"columns[{index}][search][regex]", "false")
    add("order[0][column]", str(cfg["order_column"]))
    add("order[0][dir]", "desc")
    add("start", str(start))
    add("length", str(length))
    add("search[value]")
    add("search[regex]", "false")
    add("authenticityToken", token)
    return "&".join(parts)


def list_api_url(base: str, kategori: str, tahun: int) -> str:
    """URL of the DataTables endpoint for one category."""
    cfg = CATEGORIES[kategori]
    return f"{base}/{cfg['endpoint']}{cfg['query'].format(tahun=tahun)}"


def listing_url(base: str, kategori: str, tahun: int) -> str:
    """URL of the human listing page; also the required Referer for detail pages."""
    cfg = CATEGORIES[kategori]
    suffix = f"?tahun={tahun}" if cfg["accepts_tahun"] else ""
    return f"{base}/{cfg['listing']}{suffix}"


def entry_tab_url(base: str, kategori: str, paket_id: str) -> str:
    """First tab to fetch; its nav bar reveals the package's remaining tabs."""
    return base + CATEGORIES[kategori]["entry_tab"].format(id=paket_id)


AGENCY_CSV = "output/all_lpse_urls.csv"


def slug_from_url(url: str) -> str:
    """'https://spse.inaproc.id/kemkes' -> 'kemkes'."""
    return urlparse(url.strip().rstrip("/")).path.strip("/").split("/")[-1]


def load_agencies(csv_path: str | Path = AGENCY_CSV) -> list[dict]:
    """Load the agency list, grouped by LPSE slug.

    Many kementerian/lembaga share one LPSE instance, so the CSV holds several
    rows per slug. Grouping keeps the dropdown and the output tree keyed by the
    thing that actually varies: the slug.
    """
    grouped: dict[str, dict] = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            url = (row.get("url") or "").strip()
            name = clean_text(row.get("name"))
            if not url:
                continue
            slug = slug_from_url(url)
            if not slug:
                continue
            entry = grouped.setdefault(
                slug, {"slug": slug, "base": url.rstrip("/"), "names": []}
            )
            if name and name not in entry["names"]:
                entry["names"].append(name)
    return sorted(grouped.values(), key=lambda a: a["slug"])


def match_agency(agencies: list[dict], query: str) -> dict | None:
    """Resolve a slug or a free-text agency name to one agency.

    Exact slug wins, then substring over slug and names, then token overlap.
    Returns None rather than guessing when nothing matches.
    """
    needle = clean_text(query).lower()
    if not needle:
        return None
    for agency in agencies:
        if agency["slug"] == needle:
            return agency
    for agency in agencies:
        haystack = " ".join([agency["slug"]] + agency["names"]).lower()
        if needle in haystack:
            return agency
    tokens = [t for t in re.split(r"\W+", needle) if len(t) > 2]
    best, best_score = None, 0
    for agency in agencies:
        haystack = " ".join([agency["slug"]] + agency["names"]).lower()
        score = sum(1 for token in tokens if token in haystack)
        if score > best_score:
            best, best_score = agency, score
    # All query tokens must match; a partial overlap (e.g. 'kementerian
    # antariksa' -> pertanian via 'kementerian') is a guess, and the docstring
    # promises None rather than guessing.
    return best if best_score == len(tokens) else None


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
      "Gecko/20100101 Firefox/133.0")

HTML_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

AJAX_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.5",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}

TOKEN_RE = re.compile(r"authenticityToken\s*=\s*'([^']+)'")


def extract_token(html_text: str) -> str:
    """Pull the CSRF token out of a listing page.

    The name is camelCase; the server returns 403 for authenticity_token.
    """
    match = TOKEN_RE.search(html_text)
    if not match:
        raise RuntimeError(
            "authenticityToken not found; response began: "
            + clean_text(html_text)[:200]
        )
    return match.group(1)


def open_session(listing: str) -> tuple[requests.Session, str]:
    """Warm a session on a listing page and return it with a fresh CSRF token."""
    session = requests.Session()
    session.headers.update(HTML_HEADERS)
    response = session.get(listing, allow_redirects=True, timeout=60)
    response.raise_for_status()
    return session, extract_token(response.text)


def fetch_html(session, url: str, referer: str, retries: int = MAX_RETRIES,
               log=print) -> str | None:
    """GET one detail page. Returns None when the page is unavailable.

    The Referer header is mandatory: SPSE answers 403 Akses Ditolak without it
    even on a session that already holds valid cookies.
    """
    for attempt in range(1, retries + 1):
        try:
            response = session.get(
                url, headers={**HTML_HEADERS, "Referer": referer}, timeout=60
            )
            if response.status_code == 200:
                return response.text
            if response.status_code in (403, 404):
                # A tab the package genuinely lacks; not worth retrying.
                log(f"    {response.status_code} {url}")
                return None
            log(f"    HTTP {response.status_code} {url} (attempt {attempt})")
        except Exception as err:  # network hiccup
            log(f"    {type(err).__name__}: {err} (attempt {attempt})")
        if attempt < retries:
            time.sleep(5 * attempt)
    return None


def paginate_list(session, api_url: str, token: str, kategori: str,
                  page_size: int = PAGE_SIZE, cap: int = 200000,
                  referer: str = "", log=print) -> list:
    """Fetch every row of one category by paging the DataTables endpoint.

    Stops on an empty or short page. Never trusts recordsTotal, which SPSE
    hardcodes to Integer.MAX_VALUE. Raises RuntimeError when a page still
    fails after MAX_RETRIES attempts, so a partial list is never cached.
    """
    rows: list = []
    start = 0
    while len(rows) < cap:
        page: list = []
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                body = build_dt_body(token, kategori, start, page_size)
                response = session.post(
                    api_url, data=body,
                    headers={**AJAX_HEADERS, "Referer": referer},
                    timeout=180,
                )
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                payload = response.json()
                page = payload.get("data", [])
                break
            except Exception as err:
                log(f"  start={start} attempt {attempt}/{MAX_RETRIES}: {err}")
                if attempt < MAX_RETRIES:
                    time.sleep(5 * attempt)
        else:
            # The loop never broke, so every attempt on this page failed.
            # Raising (rather than treating it as end-of-data) keeps
            # scrape_json from caching a silently partial list.json.
            raise RuntimeError(
                f"pagination failed at start={start} after {MAX_RETRIES} attempts"
            )
        if not page:
            break
        rows.extend(page)
        log(f"  start={start} -> +{len(page)} rows (total {len(rows)})")
        if len(page) < page_size:
            break
        start += len(page)
        time.sleep(DELAY_S)
    return rows


def scrape_json(base: str, slug: str, kategori: str, tahun: int,
                out_dir: Path, force: bool = False, log=print) -> list:
    """Phase 2. Download the category's row list and cache it as list.json."""
    cfg = CATEGORIES[kategori]
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "list.json"
    if cache.exists() and cache.stat().st_size > MIN_FILE_SIZE and not force:
        log(f"list.json sudah ada, dipakai ulang ({cache})")
        return json.loads(cache.read_text(encoding="utf-8"))["data"]

    listing = listing_url(base, kategori, tahun)
    log(f"Membuka {listing}")
    session, token = open_session(listing)
    rows = paginate_list(
        session, list_api_url(base, kategori, tahun), token, kategori,
        referer=listing, log=log,
    )
    cache.write_text(
        json.dumps({"data": rows}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "meta.json").write_text(
        json.dumps({
            "slug": slug, "kategori": kategori, "tahun": tahun,
            "rows": len(rows), "page_size": PAGE_SIZE,
            "accepts_tahun": cfg["accepts_tahun"],
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, indent=2), encoding="utf-8"
    )
    log(f"Tersimpan {len(rows)} baris ke {cache}")
    return rows


def tab_filename(url: str) -> str:
    """Derive a stable filename from a tab url, ignoring its query string."""
    path = _urlparse(url).path.rstrip("/")
    return (path.split("/")[-1] or "index") + ".html"


def _is_complete(path: Path) -> bool:
    """A file over MIN_FILE_SIZE counts as done; smaller means an error page."""
    return path.exists() and path.stat().st_size > MIN_FILE_SIZE


def scrape_package_html(session, base: str, kategori: str, paket_id: str,
                        out_dir: Path, referer: str, fetch=fetch_html,
                        log=print) -> int:
    """Download every tab of one package. Returns the number of files written.

    Fetches the entry tab first, reads its nav bar to learn which tabs this
    package actually has, then fetches the rest. Tab sets vary per package, so
    discovery beats a hardcoded list.
    """
    target = out_dir / str(paket_id)
    entry_url = entry_tab_url(base, kategori, paket_id)
    entry_path = target / tab_filename(entry_url)

    written = 0
    if _is_complete(entry_path):
        entry_html = entry_path.read_text(encoding="utf-8", errors="replace")
    else:
        entry_html = fetch(session, entry_url, referer=referer, log=log)
        if entry_html is None:
            return 0
        target.mkdir(parents=True, exist_ok=True)
        entry_path.write_text(entry_html, encoding="utf-8")
        written += 1

    tabs = find_tabs(entry_html)
    if not tabs:
        # find_tabs() == [] means "not a detail page" -- a fetch failure,
        # error page, or login redirect -- never "a package with no tabs":
        # every real detail page carries at least a Pengumuman tab. Log it
        # so the package reads as suspicious, not silently complete.
        log(f"    {entry_url}: tidak ada tab (bukan halaman detail?)")
    for tab in tabs:
        path = target / tab_filename(tab["url"])
        if _is_complete(path):
            continue
        html_text = fetch(session, tab["url"], referer=referer, log=log)
        if html_text is None:
            continue                      # tab this package legitimately lacks
        target.mkdir(parents=True, exist_ok=True)
        path.write_text(html_text, encoding="utf-8")
        written += 1
    return written


def scrape_html(base: str, kategori: str, tahun: int, ids: list[str],
                out_dir: Path, workers: int = DEFAULT_WORKERS,
                cancel=None, progress=None, log=print) -> dict:
    """Phase 3. Download all tabs for all packages, concurrently.

    The pool fans out over packages; each package's tabs stay sequential inside
    its worker because the nav bar of the entry tab determines the rest.
    """
    listing = listing_url(base, kategori, tahun)
    session, _ = open_session(listing)
    out_dir.mkdir(parents=True, exist_ok=True)

    done = 0
    stats = {"files": 0, "failed": []}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(scrape_package_html, session, base, kategori, paket_id,
                        out_dir, listing, log=lambda *a: None): paket_id
            for paket_id in ids
        }
        for future in as_completed(futures):
            paket_id = futures[future]
            done += 1
            try:
                stats["files"] += future.result()
            except Exception as err:
                log(f"  paket {paket_id} gagal: {type(err).__name__}: {err}")
                stats["failed"].append(paket_id)
            if progress:
                progress(done, len(ids))
            if done % 25 == 0:
                log(f"  {done}/{len(ids)} paket, {stats['files']} file baru")
            if cancel is not None and cancel.is_set():
                log("  dibatalkan pengguna")
                for pending in futures:
                    pending.cancel()
                break

    if stats["failed"]:
        (out_dir / "failed.json").write_text(
            json.dumps(stats["failed"], indent=2), encoding="utf-8")
        log(f"  {len(stats['failed'])} paket gagal, dicatat di failed.json")
    return stats


# Indonesian detail-page labels -> stable snake_case CSV columns. Labels differ
# between the five categories, which is why this is a map rather than a fixed
# per-category column list. Anything absent here survives in extra_json.
LABEL_MAP = {
    "Kode Paket": "kode_paket",
    "Kode Swakelola": "kode_paket",
    "Nama Paket": "nama_paket",
    "Nama Tender": "nama_paket",
    "Nama Swakelola": "nama_paket",
    "Satuan Kerja": "satuan_kerja",
    "K/L/PD/Instansi Lainnya": "instansi",
    "K/L/PD": "instansi",
    "Jenis Pengadaan": "jenis_pengadaan",
    "Metode Pengadaan": "metode_pengadaan",
    "Tahap Paket Saat Ini": "tahap",
    "Status Paket": "tahap",
    "Pagu": "pagu",
    "Nilai Pagu Paket": "pagu",
    "HPS": "hps",
    "Nilai HPS Paket": "hps",
    "Tanggal Pembuatan": "tanggal_pembuatan",
    "Tanggal Paket Selesai": "tanggal_selesai",
    "Tahun Anggaran": "tahun_anggaran",
    "Lokasi Pekerjaan": "lokasi",
    "Tipe Pelaksana": "tipe_pelaksana",
    "Tipe Pelaksana Swakelola": "tipe_pelaksana",
    "Nilai Total Realisasi": "nilai_realisasi",
}

MONEY_COLUMNS = ("pagu", "hps", "harga_kontrak", "nilai_realisasi")
DATE_COLUMNS = ("tanggal_pembuatan", "tanggal_selesai")

CSV_COLUMNS = [
    "slug", "nama_instansi", "kategori", "tahun",
    "kode_paket", "nama_paket", "instansi", "satuan_kerja",
    "jenis_pengadaan", "metode_pengadaan", "tahap",
    "pagu", "pagu_num", "hps", "hps_num",
    "tanggal_pembuatan", "tanggal_pembuatan_iso",
    "tanggal_selesai", "tanggal_selesai_iso",
    "tahun_anggaran", "lokasi", "tipe_pelaksana",
    "kode_rup", "sumber_dana",
    "nama_pemenang", "alamat", "npwp",
    "harga_kontrak", "harga_kontrak_num", "nilai_pdn", "nilai_umk",
    "nilai_realisasi", "nilai_realisasi_num",
    "sumber_url", "extra_json",
]


def build_rows(detail: dict, slug: str, nama_instansi: str, kategori: str,
               tahun: int, paket_id: str, sumber_url: str) -> list[dict]:
    """Flatten one parsed detail page into CSV rows, one per participant."""
    base_row = {column: "" for column in CSV_COLUMNS}
    base_row.update({
        "slug": slug, "nama_instansi": nama_instansi, "kategori": kategori,
        "tahun": tahun, "kode_paket": paket_id, "sumber_url": sumber_url,
    })

    extra: dict[str, object] = {}
    for label, value in detail["fields"].items():
        column = LABEL_MAP.get(label)
        if column:
            base_row[column] = value
        else:
            extra[label] = value

    tables = detail["named_tables"]
    rup = tables.get("rup")
    if rup and rup["rows"]:
        first = rup["rows"][0]
        if len(first) >= 3:
            base_row["kode_rup"], _, base_row["sumber_dana"] = first[0], first[1], first[2]

    realisasi = tables.get("realisasi")
    if realisasi and realisasi["rows"]:
        extra["realisasi"] = realisasi["rows"]

    # An awarded page can carry an empty pemenang table alongside a populated
    # peserta one, so pick the table that actually has rows rather than the
    # first key that exists.
    participants = None
    for key in ("pemenang", "peserta"):
        table = tables.get(key)
        if table and table["rows"]:
            participants = table
            break

    rows: list[dict] = []
    if participants:
        header = [clean_text(h) for h in participants["header"]]
        for values in participants["rows"]:
            row = dict(base_row)
            cells = dict(zip(header, values))
            row["nama_pemenang"] = cells.get("Nama Pemenang") or cells.get("Nama Peserta", "")
            row["alamat"] = cells.get("Alamat", "")
            row["npwp"] = cells.get("NPWP", "")
            row["harga_kontrak"] = cells.get("Harga Kontrak", "")
            row["nilai_pdn"] = cells.get("Nilai PDN", "")
            row["nilai_umk"] = cells.get("Nilai UMK", "")
            rows.append(row)
    else:
        rows.append(dict(base_row))

    for row in rows:
        # 'None if unparseable, otherwise the value' -- not `or ""`, which
        # would turn a legitimate 0.0 into a blank. 'Rp. 0,00' is 4 of the 7
        # distinct money values in the fixtures, so `or ""` would report
        # 'realisasi is zero' as 'realisasi is unknown'.
        for column in MONEY_COLUMNS:
            nilai = parse_rupiah(row.get(column))
            row[f"{column}_num"] = "" if nilai is None else nilai
        for column in DATE_COLUMNS:
            tanggal = parse_tanggal(row.get(column))
            row[f"{column}_iso"] = "" if tanggal is None else tanggal
        row["extra_json"] = json.dumps(extra, ensure_ascii=False) if extra else ""
    return rows


def merge_package_detail(package_dir: Path) -> dict | None:
    """Combine every saved tab of one package into a single parsed detail.

    Later tabs add fields and tables; earlier values win on conflict so the
    pengumuman page stays authoritative for shared labels.
    """
    files = sorted(package_dir.glob("*.html"))
    if not files:
        return None
    merged = {"fields": {}, "tables": [], "named_tables": {}, "tabs": []}
    for path in files:
        detail = parse_detail(path.read_text(encoding="utf-8", errors="replace"))
        for label, value in detail["fields"].items():
            merged["fields"].setdefault(label, value)
        merged["tables"].extend(detail["tables"])
        for key, table in detail["named_tables"].items():
            if key not in merged["named_tables"] or table["rows"]:
                merged["named_tables"][key] = table
        merged["tabs"] = merged["tabs"] or detail["tabs"]
    return merged


def export_csv(packages_dir: Path, out_path: Path, slug: str, nama_instansi: str,
               kategori: str, tahun: int, base: str, log=print) -> int:
    """Phase 4. Walk saved HTML, parse, and write the combined CSV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(out_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, delimiter="|",
                                extrasaction="ignore")
        writer.writeheader()
        for package_dir in sorted(p for p in packages_dir.iterdir() if p.is_dir()):
            detail = merge_package_detail(package_dir)
            if detail is None:
                continue
            rows = build_rows(
                detail, slug=slug, nama_instansi=nama_instansi, kategori=kategori,
                tahun=tahun, paket_id=package_dir.name,
                sumber_url=entry_tab_url(base, kategori, package_dir.name),
            )
            for row in rows:
                writer.writerow(row)
                written += 1
    log(f"CSV: {written} baris -> {out_path}")
    return written


def export_excel(csv_path: Path, log=print) -> Path | None:
    """Convert the CSV to .xlsx. openpyxl is imported here so the normal path
    keeps requests as the only dependency."""
    try:
        from openpyxl import Workbook
    except ImportError:
        log("openpyxl belum terpasang; lewati Excel (uv add openpyxl)")
        return None
    workbook = Workbook()
    sheet = workbook.active
    with open(csv_path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle, delimiter="|"):
            sheet.append(row)
    xlsx_path = csv_path.with_suffix(".xlsx")
    workbook.save(xlsx_path)
    log(f"Excel: {xlsx_path}")
    return xlsx_path


OUTPUT_ROOT = Path("output")


def run_dir(slug: str, tahun: int, kategori: str, root: Path = OUTPUT_ROOT) -> Path:
    """output/<slug>/<tahun>/<kategori>/ — the folder one run owns."""
    return Path(root) / slug / str(tahun) / kategori


def run_pipeline(agency: dict, kategori: str, tahun: int,
                 do_json: bool = True, do_html: bool = True, do_csv: bool = True,
                 workers: int = DEFAULT_WORKERS, excel: bool = False,
                 limit: int = 0, root: Path = OUTPUT_ROOT,
                 cancel=None, progress=None, log=print) -> dict:
    """Run the four phases for one agency, category and year.

    Each phase is skippable and resumable, so a cancelled run continues from
    what is already on disk.
    """
    base, slug = agency["base"], agency["slug"]
    nama = agency["names"][0] if agency["names"] else slug
    out_dir = run_dir(slug, tahun, kategori, root)
    html_dir = out_dir / "html"
    cfg = CATEGORIES[kategori]

    log(f"=== {cfg['label']} | {slug} | {tahun} ===")
    rows: list = []
    if do_json:
        rows = scrape_json(base, slug, kategori, tahun, out_dir, log=log)
    else:
        cache = out_dir / "list.json"
        if cache.exists():
            rows = json.loads(cache.read_text(encoding="utf-8"))["data"]
            log(f"Memakai {len(rows)} baris dari list.json")

    if not cfg["accepts_tahun"] and rows:
        before = len(rows)
        rows = filter_rows_by_year(rows, tahun)
        log(f"Filter tahun {tahun}: {before} -> {len(rows)} baris")

    ids = extract_ids(rows, kategori)
    if limit:
        ids = ids[:limit]
    log(f"{len(ids)} paket")

    stats = {"paket": len(ids), "files": 0, "csv_rows": 0}
    if do_html and ids:
        html_stats = scrape_html(base, kategori, tahun, ids, html_dir,
                                 workers=workers, cancel=cancel,
                                 progress=progress, log=log)
        stats["files"] = html_stats["files"]

    if do_csv and html_dir.exists():
        csv_path = out_dir.parent / f"{slug}_{tahun}_{kategori}.csv"
        stats["csv_rows"] = export_csv(html_dir, csv_path, slug=slug,
                                       nama_instansi=nama, kategori=kategori,
                                       tahun=tahun, base=base, log=log)
        if excel:
            export_excel(csv_path, log=log)
    return stats


def launch_gui() -> None:
    """Open the desktop window. All Tk access stays on the main thread."""
    import queue
    import threading
    import tkinter as tk
    from tkinter import ttk

    agencies = load_agencies()
    labels = [f"{a['slug']} - {a['names'][0] if a['names'] else ''}" for a in agencies]
    by_label = dict(zip(labels, agencies))

    root = tk.Tk()
    root.title("SPSE Scraper")
    root.geometry("640x620")

    messages: queue.Queue = queue.Queue()
    cancel = threading.Event()
    worker: dict[str, threading.Thread | None] = {"thread": None}

    frame = ttk.Frame(root, padding=10)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Instansi").grid(row=0, column=0, sticky="w")
    agency_var = tk.StringVar()
    agency_box = ttk.Combobox(frame, textvariable=agency_var, values=labels, width=60)
    agency_box.grid(row=0, column=1, columnspan=3, sticky="we", pady=2)

    def filter_agencies(_event=None) -> None:
        """Typeahead: 734 entries are unusable without filtering."""
        needle = agency_var.get().lower()
        agency_box["values"] = [l for l in labels if needle in l.lower()] or labels

    agency_box.bind("<KeyRelease>", filter_agencies)

    ttk.Label(frame, text="Tipe").grid(row=1, column=0, sticky="w")
    tipe_var = tk.StringVar(value="tender")
    ttk.Combobox(frame, textvariable=tipe_var, values=sorted(CATEGORIES),
                 state="readonly", width=24).grid(row=1, column=1, sticky="w", pady=2)

    ttk.Label(frame, text="Tahun").grid(row=1, column=2, sticky="e")
    tahun_var = tk.StringVar(value=str(date.today().year))
    years = [str(y) for y in range(date.today().year, 2010, -1)]
    ttk.Combobox(frame, textvariable=tahun_var, values=years, width=8
                 ).grid(row=1, column=3, sticky="w", pady=2)

    ttk.Label(frame, text="Workers").grid(row=2, column=0, sticky="w")
    workers_var = tk.StringVar(value=str(DEFAULT_WORKERS))
    ttk.Spinbox(frame, from_=1, to=32, textvariable=workers_var, width=6
                ).grid(row=2, column=1, sticky="w", pady=2)

    excel_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text="Excel juga", variable=excel_var
                    ).grid(row=2, column=2, columnspan=2, sticky="w")

    phase_json = tk.BooleanVar(value=True)
    phase_html = tk.BooleanVar(value=True)
    phase_csv = tk.BooleanVar(value=True)
    phases = ttk.Frame(frame)
    phases.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 2))
    ttk.Label(phases, text="Fase:").pack(side="left")
    for text, var in (("JSON", phase_json), ("HTML", phase_html), ("CSV", phase_csv)):
        ttk.Checkbutton(phases, text=text, variable=var).pack(side="left", padx=4)

    buttons = ttk.Frame(frame)
    buttons.grid(row=4, column=0, columnspan=4, sticky="w", pady=6)

    progress_var = tk.DoubleVar(value=0)
    progress = ttk.Progressbar(frame, variable=progress_var, maximum=100)
    progress.grid(row=5, column=0, columnspan=4, sticky="we", pady=4)
    status_var = tk.StringVar(value="Siap")
    ttk.Label(frame, textvariable=status_var).grid(row=6, column=0, columnspan=4,
                                                  sticky="w")

    log_box = tk.Text(frame, height=20, wrap="none", font=("Consolas", 9))
    log_box.grid(row=7, column=0, columnspan=4, sticky="nsew", pady=(6, 0))
    frame.rowconfigure(7, weight=1)
    frame.columnconfigure(1, weight=1)

    def emit(message: str) -> None:
        messages.put(("log", message))

    def emit_progress(done: int, total: int) -> None:
        messages.put(("progress", done, total))

    def start() -> None:
        agency = by_label.get(agency_var.get()) or match_agency(agencies, agency_var.get())
        if agency is None:
            emit("Pilih instansi dulu.")
            return
        if worker["thread"] and worker["thread"].is_alive():
            emit("Masih berjalan.")
            return
        cancel.clear()
        progress_var.set(0)
        status_var.set("Berjalan...")

        def job() -> None:
            try:
                run_pipeline(
                    agency, tipe_var.get(), resolve_tahun(int(tahun_var.get() or 0)),
                    do_json=phase_json.get(), do_html=phase_html.get(),
                    do_csv=phase_csv.get(), workers=int(workers_var.get()),
                    excel=excel_var.get(), cancel=cancel,
                    progress=emit_progress, log=emit,
                )
                messages.put(("done", "Selesai"))
            except Exception as err:
                messages.put(("done", f"Gagal: {type(err).__name__}: {err}"))

        worker["thread"] = threading.Thread(target=job, daemon=True)
        worker["thread"].start()

    def stop() -> None:
        cancel.set()
        status_var.set("Membatalkan... (file yang sudah selesai tetap tersimpan)")

    def close() -> None:
        cancel.set()
        root.after(200, root.destroy)

    ttk.Button(buttons, text="Mulai", command=start).pack(side="left")
    ttk.Button(buttons, text="Batal", command=stop).pack(side="left", padx=4)
    ttk.Button(buttons, text="Tutup", command=close).pack(side="left")
    root.protocol("WM_DELETE_WINDOW", close)

    def pump() -> None:
        """Drain the worker's queue on the main thread, 10 times a second."""
        while True:
            try:
                message = messages.get_nowait()
            except queue.Empty:
                break
            if message[0] == "log":
                log_box.insert("end", str(message[1]) + "\n")
                log_box.see("end")
            elif message[0] == "progress":
                done, total = message[1], message[2]
                progress_var.set(100 * done / total if total else 0)
                status_var.set(f"{done}/{total} paket")
            elif message[0] == "done":
                status_var.set(str(message[1]))
                progress_var.set(100)
        root.after(100, pump)

    root.after(100, pump)
    root.mainloop()


def resolve_tahun(value: int | None) -> int:
    """Default the fiscal year to the current one when unspecified."""
    return int(value) if value else date.today().year


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spse.py",
        description="Scrape SPSE procurement data. No arguments opens the GUI.",
    )
    parser.add_argument("--agency", help="LPSE slug or agency name, e.g. jakarta")
    parser.add_argument("--tipe", choices=sorted(CATEGORIES),
                        help="Procurement category")
    parser.add_argument("--tahun", type=int, help="Fiscal year (default: current)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--limit", type=int, default=0,
                        help="Only the first N packages (0 = all)")
    parser.add_argument("--csv", default=AGENCY_CSV, help="Agency list csv")
    parser.add_argument("--out", default=str(OUTPUT_ROOT), help="Output root")
    parser.add_argument("--excel", action="store_true", help="Also write .xlsx")
    parser.add_argument("--skip-json", action="store_true")
    parser.add_argument("--skip-html", action="store_true")
    parser.add_argument("--skip-csv", action="store_true")
    parser.add_argument("--dry", action="store_true",
                        help="Count packages only, download nothing")
    parser.add_argument("--list-agencies", action="store_true",
                        help="Print slug and names, then exit")
    return parser


def run_cli(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    agencies = load_agencies(args.csv)

    if args.list_agencies:
        for agency in agencies:
            print(f"{agency['slug']}\t{' ; '.join(agency['names'])}")
        return 0

    if not args.agency or not args.tipe:
        print("Butuh --agency dan --tipe. Lihat --help atau --list-agencies.")
        return 2

    agency = match_agency(agencies, args.agency)
    if agency is None:
        print(f"Instansi '{args.agency}' tidak ditemukan. Coba --list-agencies.")
        return 3

    tahun = resolve_tahun(args.tahun)
    if args.dry:
        rows = scrape_json(agency["base"], agency["slug"], args.tipe, tahun,
                           run_dir(agency["slug"], tahun, args.tipe, Path(args.out)))
        if not CATEGORIES[args.tipe]["accepts_tahun"]:
            rows = filter_rows_by_year(rows, tahun)
        print(f"{agency['slug']} {args.tipe} {tahun}: {len(rows)} paket")
        return 0

    stats = run_pipeline(
        agency, args.tipe, tahun,
        do_json=not args.skip_json, do_html=not args.skip_html,
        do_csv=not args.skip_csv, workers=args.workers, excel=args.excel,
        limit=args.limit, root=Path(args.out),
    )
    print(f"Selesai: {stats['paket']} paket, {stats['files']} file baru, "
          f"{stats['csv_rows']} baris CSV")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        launch_gui()
        return 0
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())

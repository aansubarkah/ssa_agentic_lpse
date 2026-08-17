"""spse.py — scrape procurement data from https://spse.inaproc.id.

Run with no arguments for a Tkinter GUI; run with arguments for a headless
CLI suitable for automation. See SPSE_SCRAPER.md for the site contract and
docs/plans/2026-08-17-spse-scraper-gui-design.md for the design rationale.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse

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

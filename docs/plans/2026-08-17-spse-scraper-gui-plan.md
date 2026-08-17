# SPSE Scraper with GUI — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `spse.py`, a single Python file that scrapes procurement data from
https://spse.inaproc.id for any agency, year, and category, driven either by a
Tkinter GUI or by CLI arguments for an AI agent, and exports a combined CSV.

**Architecture:** Four independent, resumable phases (agencies, list JSON, detail
HTML, CSV export) behind a category table that holds all site-specific knowledge.
A generic `parse_detail()` handles every category because all SPSE detail pages
share one markup contract. The HTML phase fans out over packages with a thread
pool; the GUI runs the same code in a worker thread and communicates through a
queue.

**Tech Stack:** Python 3.14, `requests`, stdlib `tkinter` / `html.parser` /
`concurrent.futures`; `pytest` for tests (dev-only); `openpyxl` lazily imported
for optional Excel output.

**Design document:** `docs/plans/2026-08-17-spse-scraper-gui-design.md` — read it
first. It records the verified site facts (mandatory `Referer` header, the
`th.bgwarning` contract, the `recordsTotal` trap) that this plan depends on.

---

## Context an engineer new to this repo needs

**The site.** SPSE is Indonesia's government e-procurement platform. Each agency
("instansi") has its own path prefix, e.g. `https://spse.inaproc.id/kemkes`. Under
each agency there are five categories of procurement records. A category has a
listing page (server-rendered HTML) and a DataTables JSON API. Each record
("paket") has several detail tabs rendered as HTML.

**Indonesian terms** you will see in labels and will not need to translate — keep
them verbatim as dict keys: *paket* (package), *tender*, *non tender*,
*pencatatan* (recording), *swakelola* (self-managed), *darurat* (emergency),
*pagu* (budget ceiling), *HPS* (owner's estimate), *pemenang* (winner), *peserta*
(participant), *satuan kerja* (work unit), *tahun anggaran* (fiscal year).

**Three traps that will waste your day if you miss them:**

1. `authenticityToken` is **camelCase**. `authenticity_token` returns 403.
2. `recordsTotal` in every API response is `2147483647` (Java
   `Integer.MAX_VALUE`), not a real count. Paginate until an empty or short page.
3. Detail pages return `403 Akses Ditolak!` unless the request carries a
   `Referer` header pointing at the category listing page — even with valid
   session cookies.

**Existing code to read, not modify.** `spse_pipeline.py` and
`scrape_lelang_batch.py` show the working request shapes. `scrape_darurat_batch.py`
shows the DataTables body builder. Do not edit any of them; `spse.py` replaces
them but they stay as reference.

**Fixtures.** `html_examples/` holds six real detail pages, one per category plus
two tender variants. All parser tests run against these, offline. Filenames
contain spaces — quote them.

| Fixture | Category | Package | Tabs | `th.bgwarning` fields |
|---|---|---|---|---|
| `LPSE - Informasi Tender.htm` | tender, pemenangberkontrak | 10102453000 | 5 | 6 |
| `LPSE - Informasi Tender2.htm` | tender, peserta (unawarded) | 10158661000 | 2 | 0 |
| `LPSE - Informasi Paket.htm` | non tender, pengumumanpl | 11002302000 | 5 | 18 |
| `LPSE - Informasi Paket2.htm` | pencatatan, pengumumannonspk | 11024357000 | 2 | 10 |
| `LPSE - Informasi Swakelola.htm` | swakelola, pelaksana | 1176047 | 2 | 7 |
| `LPSE - Informasi Pengadaan Darurat.htm` | darurat, pemenang | 2047 | 2 | 9 |

**Testing philosophy.** Every pure function gets a test written *before* the
implementation. Network code is tested against a fake session object, never
against the live site — live verification happens once, at the end, in Task 19.
Tests assert on specific values taken from the fixtures above, not on shapes:
`assert fields["Pagu"] == "Rp. 787.406.000,00"`, not `assert len(fields) > 0`.

**Never use emoji in any file** — repo rule from `CLAUDE.md`.

---

## Task 1: Test scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Create: `tests/test_fixtures.py`

**Step 1: Add pytest as a dev dependency and put the repo root on `sys.path`**

In `pyproject.toml`, add:

```toml
[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

Run: `uv sync --group dev`
Expected: pytest installed.

`pythonpath = ["."]` is load-bearing, not cosmetic. The project has no
`[build-system]`, so `uv` treats it as a virtual project and never installs it
into the venv. Every later task imports the module under test as
`from spse import ...`, and that only resolves because this setting puts the repo
root on `sys.path`. Without it the suite fails with
`ModuleNotFoundError: No module named 'spse'`. Do not rely on `tests/__init__.py`
for this instead: pytest's `prepend` import mode does happen to insert the repo
root when `tests/` is a package, but that makes an apparently-empty boilerplate
file load-bearing and is far too easy to delete by accident.

**Step 2: Create the fixture helper**

`tests/conftest.py`:

```python
"""Shared test fixtures: paths to the saved SPSE detail pages."""

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "html_examples"

FIXTURES = {
    "tender_pemenang": "LPSE - Informasi Tender.htm",
    "tender_peserta": "LPSE - Informasi Tender2.htm",
    "nontender_pengumuman": "LPSE - Informasi Paket.htm",
    "pencatatan_pengumuman": "LPSE - Informasi Paket2.htm",
    "swakelola_pelaksana": "LPSE - Informasi Swakelola.htm",
    "darurat_pemenang": "LPSE - Informasi Pengadaan Darurat.htm",
}


@pytest.fixture
def load_fixture():
    """Return a function that reads a saved detail page by short name."""

    def _load(name: str) -> str:
        path = FIXTURE_DIR / FIXTURES[name]
        return path.read_text(encoding="utf-8", errors="replace")

    return _load
```

**Step 3: Verify the fixtures are reachable**

Create `tests/test_fixtures.py`:

```python
import pytest

FIXTURE_NAMES = [
    "tender_pemenang",
    "tender_peserta",
    "nontender_pengumuman",
    "pencatatan_pengumuman",
    "swakelola_pelaksana",
    "darurat_pemenang",
]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_loads(load_fixture, name):
    assert "nav-tabs" in load_fixture(name)
```

Parametrize rather than looping inside one test: each fixture gets its own test ID,
so a broken or missing page is named in the output instead of aborting the whole
check at the first failure.

Run: `uv run pytest tests/test_fixtures.py -v`
Expected: 6 passed, one per fixture.

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock tests/
git commit -m "test: add pytest scaffolding and fixture loader"
```

---

## Task 2: Value cleaners

Small pure functions used everywhere. Written first because everything depends on
them.

**Files:**
- Create: `spse.py`
- Create: `tests/test_clean.py`

**Step 1: Write the failing tests**

`tests/test_clean.py`:

```python
from spse import clean_text, parse_rupiah, parse_tanggal


def test_clean_text_collapses_whitespace_and_nbsp():
    assert clean_text("  APBN 2026\xa0\xa0\n ") == "APBN 2026"


def test_clean_text_handles_empty():
    assert clean_text("") == ""
    assert clean_text(None) == ""


def test_parse_rupiah_indonesian_format():
    assert parse_rupiah("Rp. 787.406.000,00") == 787406000.00
    assert parse_rupiah("Rp. 663.823.912.000,00") == 663823912000.00
    assert parse_rupiah("Rp. 0,00") == 0.0


def test_parse_rupiah_accepts_bare_numbers_without_the_rp_prefix():
    # The winner sub-tables (Harga Kontrak, Nilai PDN, Nilai UMK) are empty in
    # every fixture, so we do not know whether they carry the 'Rp' prefix.
    # Accept both shapes rather than risk blanking real contract prices.
    assert parse_rupiah("Rp 0,00") == 0.0
    assert parse_rupiah("1.000.000,00") == 1000000.00
    assert parse_rupiah("0,00") == 0.0
    assert parse_rupiah("165146000") == 165146000.0


def test_parse_rupiah_returns_none_when_unparseable():
    assert parse_rupiah("") is None
    assert parse_rupiah("-") is None
    assert parse_rupiah("Lumsum") is None


def test_parse_rupiah_rejects_non_money_values_seen_in_real_fixtures():
    # Every string below is a real cell value scraped from html_examples/.
    # Stripping non-digits made each one yield a bogus float, e.g.
    # 'APBN 2026' -> 2026.0 and '11 Agustus 2026' -> 112026.0.
    assert parse_rupiah("APBN 2026") is None
    assert parse_rupiah("11 Agustus 2026") is None
    assert parse_rupiah("Peserta 3") is None
    assert parse_rupiah("2 peserta") is None
    assert parse_rupiah("APOTEK KIMIA FARMA 103 SAMPIT") is None


def test_parse_tanggal_indonesian_month_names():
    assert parse_tanggal("11 Agustus 2026") == "2026-08-11"
    assert parse_tanggal("6 Agustus 2026") == "2026-08-06"
    assert parse_tanggal("10 September 2021") == "2021-09-10"
    assert parse_tanggal("12 Maret 2024") == "2024-03-12"


def test_parse_tanggal_returns_none_when_unparseable():
    assert parse_tanggal("") is None
    assert parse_tanggal("Paket Sudah Selesai") is None
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_clean.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spse'`.

**Step 3: Create `spse.py` with the module header and cleaners**

```python
"""spse.py — scrape procurement data from https://spse.inaproc.id.

Run with no arguments for a Tkinter GUI; run with arguments for a headless
CLI suitable for automation. See SPSE_SCRAPER.md for the site contract and
docs/plans/2026-08-17-spse-scraper-gui-design.md for the design rationale.
"""

from __future__ import annotations

import re
import sys


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

BULAN = {
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
    """Collapse whitespace and non-breaking spaces into single spaces."""
    if not value:
        return ""
    return _WS_RE.sub(" ", value.replace("\xa0", " ")).strip()


def parse_rupiah(value: str | None) -> float | None:
    """'Rp. 787.406.000,00' -> 787406000.0; None when not a currency string."""
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
    """'11 Agustus 2026' -> '2026-08-11'; None when not a date."""
    match = _TANGGAL_RE.match(clean_text(value))
    if not match:
        return None
    day, month_name, year = match.groups()
    month = BULAN.get(month_name.lower())
    if not month:
        return None
    return f"{year}-{month:02d}-{int(day):02d}"
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_clean.py -v`
Expected: 8 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_clean.py
git commit -m "feat: add value cleaners for text, rupiah and Indonesian dates"
```

---

## Task 3: Tab discovery from the nav bar

**Files:**
- Modify: `spse.py`
- Create: `tests/test_parse_tabs.py`

**Step 1: Write the failing tests**

`tests/test_parse_tabs.py`:

```python
from spse import find_tabs


def test_finds_five_tender_tabs(load_fixture):
    tabs = find_tabs(load_fixture("tender_pemenang"))
    assert len(tabs) == 5
    assert tabs[0]["url"].endswith("/lelang/10102453000/pengumumanlelang")
    assert tabs[-1]["url"].endswith("/evaluasi/10102453000/pemenangberkontrak")


def test_marks_the_active_tab(load_fixture):
    tabs = find_tabs(load_fixture("tender_pemenang"))
    active = [t for t in tabs if t["active"]]
    assert len(active) == 1
    assert active[0]["url"].endswith("pemenangberkontrak")


def test_unawarded_tender_has_only_two_tabs(load_fixture):
    # Package 10158661000 has no evaluasi tabs; that is valid, not an error.
    tabs = find_tabs(load_fixture("tender_peserta"))
    assert len(tabs) == 2
    assert [t["label"] for t in tabs] == ["Pengumuman", "Peserta"]


def test_query_string_tab_urls_are_preserved(load_fixture):
    tabs = find_tabs(load_fixture("pencatatan_pengumuman"))
    assert len(tabs) == 2
    assert tabs[-1]["url"].endswith("pengumumannonspkpemenang?id=11024357000")


def test_swakelola_tab_labels(load_fixture):
    tabs = find_tabs(load_fixture("swakelola_pelaksana"))
    assert [t["label"] for t in tabs] == ["Pengumuman", "Pelaksana Swakelola"]
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_parse_tabs.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_tabs'`.

**Step 3: Implement**

Add to `spse.py`. Note: use `html.parser`, **not** regexes over tag strings —
tags carry unpredictable extra attributes (`<div class="content" style="...">`).

```python
from html.parser import HTMLParser


class _TabParser(HTMLParser):
    """Collect the `a.nav-link` entries of the detail-page tab bar."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabs: list[dict] = []
        self._current: dict | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag != "a":
            return
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if "nav-link" not in classes or not attr.get("href"):
            return
        self._current = {
            "url": attr["href"],
            "active": "active" in classes,
            "label": "",
        }

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["label"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current is not None:
            self._current["label"] = clean_text(self._current["label"])
            self.tabs.append(self._current)
            self._current = None


def find_tabs(html_text: str) -> list[dict]:
    """Return this package's real tabs: [{'url', 'label', 'active'}, ...].

    SPSE renders absolute hrefs here, and the set varies per package (an
    unawarded tender has no evaluasi tabs), so this is the authority on which
    tabs to fetch rather than a hardcoded table.
    """
    parser = _TabParser()
    parser.feed(html_text)
    return parser.tabs
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_parse_tabs.py -v`
Expected: 5 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_parse_tabs.py
git commit -m "feat: discover detail-page tabs from the rendered nav bar"
```

---

## Task 4: `parse_detail` — label/value fields

**Files:**
- Modify: `spse.py`
- Create: `tests/test_parse_detail.py`

**Step 1: Write the failing tests**

`tests/test_parse_detail.py`:

```python
from spse import parse_detail


def test_tender_fields(load_fixture):
    result = parse_detail(load_fixture("tender_pemenang"))
    fields = result["fields"]
    assert len(fields) == 6
    assert fields["Nama Tender"].startswith("Paket Jasa Lainnya Pertemuan")
    assert fields["Jenis Pengadaan"] == "Jasa Lainnya"
    assert fields["K/L/PD/Instansi Lainnya"] == "Kementerian Kesehatan"
    assert fields["Satuan Kerja"] == "SEKRETARIAT BADAN KEBIJAKAN PEMBANGUNAN KESEHATAN"
    assert fields["Pagu"] == "Rp. 787.406.000,00"
    assert fields["HPS"] == "Rp. 750.939.420,00"


def test_nontender_fields(load_fixture):
    fields = parse_detail(load_fixture("nontender_pengumuman"))["fields"]
    assert len(fields) == 18
    assert fields["Kode Paket"] == "11002302000"
    assert fields["Tahap Paket Saat Ini"] == "Paket Sudah Selesai"
    assert fields["Tanggal Pembuatan"] == "11 Agustus 2026"
    assert fields["Tahun Anggaran"] == "APBN 2026"      # nbsp stripped
    assert fields["Jenis Kontrak"] == "Lumsum"


def test_pencatatan_fields(load_fixture):
    fields = parse_detail(load_fixture("pencatatan_pengumuman"))["fields"]
    assert len(fields) == 10
    assert fields["Kode Paket"] == "11024357000"
    assert fields["Nilai Pagu Paket"] == "Rp. 124.126.000,00"


def test_swakelola_fields(load_fixture):
    fields = parse_detail(load_fixture("swakelola_pelaksana"))["fields"]
    assert len(fields) == 7
    assert fields["Tipe Pelaksana"] == "K/L/PD Penanggung Jawab Anggaran"
    assert fields["Nilai Pagu Paket"] == "Rp. 1.000.000.000,00"
    assert fields["Tanggal Paket Selesai"] == "30 Oktober 2025"


def test_darurat_fields(load_fixture):
    fields = parse_detail(load_fixture("darurat_pemenang"))["fields"]
    assert len(fields) == 9
    assert "COVID-19" in fields["Nama Paket"]
    assert fields["Metode Pengadaan"] == "Darurat"
    assert fields["Nilai Pagu Paket"] == "Rp. 663.823.912.000,00"


def test_peserta_page_has_no_label_value_fields(load_fixture):
    # The tender peserta tab renders only a participant table.
    assert parse_detail(load_fixture("tender_peserta"))["fields"] == {}


def test_tabs_are_included_in_the_result(load_fixture):
    assert len(parse_detail(load_fixture("tender_pemenang"))["tabs"]) == 5
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_parse_detail.py -v`
Expected: FAIL — `cannot import name 'parse_detail'`.

**Step 3: Implement the parser**

The markup contract, verified across all six fixtures:

- Content lives in `div.content`; the tag has extra attributes on some pages.
- A field row is `<th class="bgwarning">Label</th><td colspan="N">Value</td>`.
  No row ever holds more than one `th.bgwarning`, so every one is a label.
- Sub-tables are a nested `<table>` inside a `<td>`, with a plain, attribute-free
  `<th>` header row. Text inside a nested table must not leak into the enclosing
  cell's value, which is what the depth tracking below prevents.

```python
class _DetailParser(HTMLParser):
    """Extract label/value fields and nested sub-tables from a detail page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, str] = {}
        self.tables: list[dict] = []
        self._in_content = False
        self._content_depth = 0        # div nesting inside div.content
        self._table_depth = 0
        self._cells: list[dict] = []   # cells of the current row, innermost table
        self._cell: dict | None = None
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
        elif tag == "tr":
            self._cells = []
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
                self._cells.append(self._cell)
                self._cell = None
        elif tag == "tr":
            self._finish_row()
        elif tag == "table":
            self._finish_table()

    # -- row / table classification --------------------------------------
    def _finish_row(self) -> None:
        cells = [c for c in self._cells if c["depth"] == self._table_depth]
        self._cells = []
        if not cells:
            return
        first = cells[0]
        if first["tag"] == "th" and "bgwarning" in first["classes"]:
            value_cells = cells[1:]
            value = " ".join(c["text"] for c in value_cells if c["text"]).strip()
            links = [href for c in value_cells for href in c["links"]]
            self.fields[first["text"]] = clean_text(value)
            if links:
                self.fields.setdefault(f"{first['text']} [url]", links[0])
            return
        if self._rows_stack:
            self._rows_stack[-1].append(
                {"tags": [c["tag"] for c in cells],
                 "values": [c["text"] for c in cells]}
            )

    def _finish_table(self) -> None:
        rows = self._rows_stack.pop() if self._rows_stack else []
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


def parse_detail(html_text: str) -> dict:
    """Parse one SPSE detail page.

    Returns {'fields': {label: value}, 'tables': [...], 'tabs': [...]}.
    One parser serves all five categories because every detail page shares
    the same markup contract; see SPSE_SCRAPER.md.
    """
    parser = _DetailParser()
    parser.feed(html_text)
    return {
        "fields": parser.fields,
        "tables": parser.tables,
        "tabs": find_tabs(html_text),
    }
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_parse_detail.py -v`
Expected: 7 passed. If a field count is off by one, print `result["fields"]` and
compare against the fixture — the counts in the table above are measured, so a
mismatch means a parser bug, not a wrong expectation.

**Step 5: Commit**

```bash
git add spse.py tests/test_parse_detail.py
git commit -m "feat: add generic detail-page parser for all five categories"
```

---

## Task 5: `parse_detail` — named sub-tables

**Files:**
- Modify: `spse.py`
- Modify: `tests/test_parse_detail.py`

**Step 1: Write the failing tests**

Append to `tests/test_parse_detail.py`:

```python
def test_tender_winner_table_is_named_and_empty(load_fixture):
    # Nested table inside a td; header present, no winner rows for this package.
    tables = parse_detail(load_fixture("tender_pemenang"))["named_tables"]
    assert "pemenang" in tables
    assert tables["pemenang"]["header"] == [
        "Nama Pemenang", "Alamat", "NPWP", "Harga Kontrak", "Nilai PDN", "Nilai UMK"]
    assert tables["pemenang"]["rows"] == []


def test_peserta_table_rows(load_fixture):
    tables = parse_detail(load_fixture("tender_peserta"))["named_tables"]
    assert tables["peserta"]["header"] == ["No", "Nama Peserta"]
    assert len(tables["peserta"]["rows"]) == 5
    assert tables["peserta"]["rows"][0] == ["1", "Peserta 1"]


def test_rup_table_in_nontender(load_fixture):
    tables = parse_detail(load_fixture("nontender_pengumuman"))["named_tables"]
    assert tables["rup"]["header"] == ["Kode RUP", "Nama Paket", "Sumber Dana"]
    assert tables["rup"]["rows"][0][0] == "67643676"
    assert tables["rup"]["rows"][0][2] == "APBN"


def test_realisasi_table_in_swakelola(load_fixture):
    tables = parse_detail(load_fixture("swakelola_pelaksana"))["named_tables"]
    assert tables["realisasi"]["header"] == [
        "No.", "Jenis Realisasi", "Nilai Realisasi", "Tanggal Realisasi"]


def test_attachment_url_is_captured(load_fixture):
    fields = parse_detail(load_fixture("nontender_pengumuman"))["fields"]
    assert "/dl/" in fields["Uraian Singkat Pekerjaan [url]"]
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_parse_detail.py -v`
Expected: FAIL — `KeyError: 'named_tables'`.

**Step 3: Implement table naming**

Add to `spse.py`:

```python
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
```

Then extend the `parse_detail` return value:

```python
    tables = parser.tables
    return {
        "fields": parser.fields,
        "tables": tables,
        "named_tables": name_tables(tables),
        "tabs": find_tabs(html_text),
    }
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_parse_detail.py -v`
Expected: 12 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_parse_detail.py
git commit -m "feat: name detail-page sub-tables by header signature"
```

---

## Task 6: Category configuration table

All site-specific knowledge lives here. Adding a sixth category later must mean
adding one entry, not editing functions.

**Files:**
- Modify: `spse.py`
- Create: `tests/test_categories.py`

**Step 1: Write the failing tests**

`tests/test_categories.py`:

```python
from spse import CATEGORIES, entry_tab_url, list_api_url


def test_five_categories_are_defined():
    assert set(CATEGORIES) == {"tender", "nontender", "pencatatan", "swakelola", "darurat"}


def test_tender_list_url_includes_tahun():
    url = list_api_url("https://spse.inaproc.id/kemkes", "tender", 2025)
    assert url == "https://spse.inaproc.id/kemkes/dt/lelang?rekanan=&tahun=2025&instansiId="


def test_swakelola_list_url_has_no_tahun():
    # The endpoint ignores tahun; filtering happens client-side.
    url = list_api_url("https://spse.inaproc.id/kemkes", "swakelola", 2025)
    assert url == "https://spse.inaproc.id/kemkes/dt/swakelola"
    assert CATEGORIES["swakelola"]["accepts_tahun"] is False


def test_darurat_list_url():
    assert list_api_url("https://spse.inaproc.id/kemkes", "darurat", 2025) == \
        "https://spse.inaproc.id/kemkes/dt/darurat-list"


def test_entry_tab_urls_per_category():
    base = "https://spse.inaproc.id/kemkes"
    assert entry_tab_url(base, "tender", "10102453000") == \
        f"{base}/lelang/10102453000/pengumumanlelang"
    assert entry_tab_url(base, "nontender", "11002302000") == \
        f"{base}/nontender/11002302000/pengumumanpl"
    assert entry_tab_url(base, "pencatatan", "11024357000") == \
        f"{base}/pencatatan/pengumumannonspk?id=11024357000"
    assert entry_tab_url(base, "swakelola", "1176047") == \
        f"{base}/swakelola/1176047/pengumuman"
    assert entry_tab_url(base, "darurat", "2047") == \
        f"{base}/darurat/pengumumandarurat?id=2047"
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_categories.py -v`
Expected: FAIL — `cannot import name 'CATEGORIES'`.

**Step 3: Implement**

```python
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
```

**Note on `columns` and `order_column`:** copy the exact values from the existing
batch scripts — `scrape_lelang_batch.py` for tender, `scrape_nontender_batch.py`
for non tender, `scrape_pencatatan_batch.py`, `scrape_swakelola_batch.py`, and
`scrape_darurat_batch.py`. Do not guess; the server rejects a mismatched column
count.

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_categories.py -v`
Expected: 5 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_categories.py
git commit -m "feat: add category configuration table with URL builders"
```

---

## Task 7: Agency list from CSV

**Files:**
- Modify: `spse.py`
- Create: `tests/test_agencies.py`

**Step 1: Write the failing tests**

`tests/test_agencies.py`:

```python
from spse import load_agencies, match_agency, slug_from_url

CSV = """name,url,old_url
"Badan Karantina Indonesia > LPSE Kementerian Pertanian","https://spse.inaproc.id/pertanian","https://lpse.pertanian.go.id"
"Kementerian Pertanian > LPSE Kementerian Pertanian","https://spse.inaproc.id/pertanian","https://lpse.pertanian.go.id"
"Provinsi DKI Jakarta > LPSE Provinsi Daerah Khusus Ibukota Jakarta","https://spse.inaproc.id/jakarta","https://lpse.jakarta.go.id"
"""


def test_slug_from_url():
    assert slug_from_url("https://spse.inaproc.id/kemkes") == "kemkes"
    assert slug_from_url("https://spse.inaproc.id/jakarta/") == "jakarta"


def test_load_agencies_groups_shared_lpse(tmp_path):
    path = tmp_path / "urls.csv"
    path.write_text(CSV, encoding="utf-8")
    agencies = load_agencies(path)
    # Two K/L share the pertanian LPSE, so it appears once.
    assert [a["slug"] for a in agencies] == ["jakarta", "pertanian"]
    pertanian = [a for a in agencies if a["slug"] == "pertanian"][0]
    assert len(pertanian["names"]) == 2
    assert pertanian["base"] == "https://spse.inaproc.id/pertanian"


def test_match_agency_by_slug(tmp_path):
    path = tmp_path / "urls.csv"
    path.write_text(CSV, encoding="utf-8")
    agencies = load_agencies(path)
    assert match_agency(agencies, "jakarta")["slug"] == "jakarta"


def test_match_agency_by_partial_name(tmp_path):
    path = tmp_path / "urls.csv"
    path.write_text(CSV, encoding="utf-8")
    agencies = load_agencies(path)
    # An agent may say "pemprov dki jakarta"; "dki jakarta" must resolve.
    assert match_agency(agencies, "dki jakarta")["slug"] == "jakarta"
    assert match_agency(agencies, "Kementerian Pertanian")["slug"] == "pertanian"


def test_match_agency_returns_none_when_unknown(tmp_path):
    path = tmp_path / "urls.csv"
    path.write_text(CSV, encoding="utf-8")
    assert match_agency(load_agencies(path), "kementerian antariksa") is None


def test_real_csv_loads(tmp_path):
    # The shipped file has 734 data rows across far fewer distinct LPSE hosts.
    agencies = load_agencies("output/all_lpse_urls.csv")
    assert len(agencies) > 100
    assert any(a["slug"] == "jakarta" for a in agencies)
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_agencies.py -v`
Expected: FAIL — `cannot import name 'load_agencies'`.

**Step 3: Implement**

```python
import csv
from pathlib import Path
from urllib.parse import urlparse

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
    return best if best_score else None
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_agencies.py -v`
Expected: 6 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_agencies.py
git commit -m "feat: load and match agencies from the LPSE url csv"
```

---

## Task 8: HTTP session layer

**Files:**
- Modify: `spse.py`
- Create: `tests/test_http.py`

**Step 1: Write the failing tests**

Network code is tested against a fake session — no live requests in the suite.

`tests/test_http.py`:

```python
import pytest

from spse import extract_token, fetch_html

HTML_WITH_TOKEN = """
<script>
  var authenticityToken = 'abc123def456';
</script>
"""


class FakeResponse:
    def __init__(self, status=200, text="ok"):
        self.status_code = status
        self.text = text

    def json(self):
        return {"data": []}


class FakeSession:
    """Records the requests made so tests can assert on headers."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or [FakeResponse()]
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def test_extract_token():
    assert extract_token(HTML_WITH_TOKEN) == "abc123def456"


def test_extract_token_raises_with_snippet():
    with pytest.raises(RuntimeError) as err:
        extract_token("<html>Akses Ditolak</html>")
    assert "Akses Ditolak" in str(err.value)


def test_fetch_html_sends_referer():
    # Detail pages return 403 without a Referer, so it must always be sent.
    session = FakeSession()
    fetch_html(session, "https://spse.inaproc.id/kemkes/lelang/1/peserta",
               referer="https://spse.inaproc.id/kemkes/lelang?tahun=2025")
    _, _, kwargs = session.calls[0]
    assert kwargs["headers"]["Referer"] == "https://spse.inaproc.id/kemkes/lelang?tahun=2025"


def test_fetch_html_returns_none_on_403_without_retrying_forever():
    session = FakeSession([FakeResponse(403, "Akses Ditolak!")])
    assert fetch_html(session, "https://x/y", referer="https://x", retries=1) is None
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_http.py -v`
Expected: FAIL — `cannot import name 'extract_token'`.

**Step 3: Implement**

```python
import time

import requests

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
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_http.py -v`
Expected: 4 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_http.py
git commit -m "feat: add session warm-up, token extraction and referer-aware fetch"
```

---

## Task 9: DataTables body builder

**Files:**
- Modify: `spse.py`
- Create: `tests/test_datatables.py`

**Step 1: Write the failing tests**

`tests/test_datatables.py`:

```python
from urllib.parse import parse_qs

from spse import build_dt_body


def test_body_uses_camelcase_token():
    body = build_dt_body("tok", "tender", start=0, length=10000)
    parsed = parse_qs(body, keep_blank_values=True)
    assert parsed["authenticityToken"] == ["tok"]
    assert "authenticity_token" not in parsed


def test_body_declares_the_right_column_count():
    body = build_dt_body("tok", "tender", start=0, length=10000)
    parsed = parse_qs(body, keep_blank_values=True)
    assert "columns[15][data]" in parsed
    assert "columns[16][data]" not in parsed


def test_body_carries_start_and_length():
    body = build_dt_body("tok", "swakelola", start=300, length=100)
    parsed = parse_qs(body, keep_blank_values=True)
    assert parsed["start"] == ["300"]
    assert parsed["length"] == ["100"]
    assert parsed["draw"] == ["1"]


def test_body_order_column_matches_category():
    parsed = parse_qs(build_dt_body("tok", "tender", 0, 10), keep_blank_values=True)
    assert parsed["order[0][column]"] == ["5"]
    assert parsed["order[0][dir]"] == ["desc"]
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_datatables.py -v`
Expected: FAIL — `cannot import name 'build_dt_body'`.

**Step 3: Implement**

Model this on `build_dt_body` in `scrape_darurat_batch.py`, generalised over the
category's column count.

```python
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
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_datatables.py -v`
Expected: 4 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_datatables.py
git commit -m "feat: build DataTables post bodies per category"
```

---

## Task 10: Phase 2 — list JSON with pagination

**Files:**
- Modify: `spse.py`
- Create: `tests/test_scrape_json.py`

**Step 1: Write the failing tests**

`tests/test_scrape_json.py`:

```python
import json

from spse import paginate_list


class FakeDtSession:
    """Serves canned DataTables pages and records the bodies posted."""

    def __init__(self, pages):
        self.pages = pages
        self.bodies = []
        self.headers = {}

    def post(self, url, data=None, headers=None, timeout=None):
        self.bodies.append(data)
        index = len(self.bodies) - 1
        page = self.pages[index] if index < len(self.pages) else []

        class Response:
            status_code = 200

            @staticmethod
            def json():
                # recordsTotal is Integer.MAX_VALUE in real responses.
                return {"draw": 1, "recordsTotal": 2147483647, "data": page}

        return Response()


def test_stops_on_empty_page():
    session = FakeDtSession([[["a"], ["b"]], []])
    rows = paginate_list(session, "https://x/dt/lelang", "tok", "tender",
                         page_size=2, log=lambda *a: None)
    assert rows == [["a"], ["b"]]
    assert len(session.bodies) == 2


def test_stops_on_short_page_without_extra_request():
    session = FakeDtSession([[["a"]]])
    rows = paginate_list(session, "https://x/dt/lelang", "tok", "tender",
                         page_size=10, log=lambda *a: None)
    assert rows == [["a"]]
    assert len(session.bodies) == 1


def test_ignores_records_total():
    # A naive implementation would try to fetch 2147483647 rows.
    session = FakeDtSession([[["a"], ["b"]], [["c"], ["d"]], []])
    rows = paginate_list(session, "https://x/dt/lelang", "tok", "tender",
                         page_size=2, log=lambda *a: None)
    assert len(rows) == 4


def test_advances_start_between_pages():
    session = FakeDtSession([[["a"], ["b"]], []])
    paginate_list(session, "https://x/dt/lelang", "tok", "tender",
                  page_size=2, log=lambda *a: None)
    assert "start=0&" in session.bodies[0] + "&"
    assert "start=2&" in session.bodies[1] + "&"
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scrape_json.py -v`
Expected: FAIL — `cannot import name 'paginate_list'`.

**Step 3: Implement pagination and the phase wrapper**

```python
def paginate_list(session, api_url: str, token: str, kategori: str,
                  page_size: int = PAGE_SIZE, cap: int = 200000,
                  referer: str = "", log=print) -> list:
    """Fetch every row of one category by paging the DataTables endpoint.

    Stops on an empty or short page. Never trusts recordsTotal, which SPSE
    hardcodes to Integer.MAX_VALUE.
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
```

Add `import json` to the imports.

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_scrape_json.py -v`
Expected: 4 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_scrape_json.py
git commit -m "feat: add phase 2 list scraping with empty-page pagination"
```

---

## Task 11: Package IDs and the client-side year filter

Swakelola and darurat endpoints ignore `tahun`, so their rows must be filtered in
memory.

**Files:**
- Modify: `spse.py`
- Create: `tests/test_year_filter.py`

**Step 1: Write the failing tests**

`tests/test_year_filter.py`:

```python
from spse import extract_ids, filter_rows_by_year


def test_extract_ids_uses_the_configured_column():
    rows = [["10102453000", "Paket A"], ["10158661000", "Paket B"]]
    assert extract_ids(rows, "tender") == ["10102453000", "10158661000"]


def test_extract_ids_strips_html_from_the_cell():
    rows = [['<a href="/x">2047</a>', "Paket"]]
    assert extract_ids(rows, "darurat") == ["2047"]


def test_extract_ids_skips_blank_cells():
    assert extract_ids([["", "Paket"], ["7", "Paket"]], "tender") == ["7"]


def test_filter_rows_by_year_matches_any_cell():
    rows = [["1", "Paket A", "12 Maret 2024"], ["2", "Paket B", "30 Oktober 2025"]]
    assert filter_rows_by_year(rows, 2025) == [["2", "Paket B", "30 Oktober 2025"]]


def test_filter_rows_by_year_keeps_rows_with_no_date():
    # Better to keep an undated row than to silently drop real data.
    rows = [["1", "Paket tanpa tanggal"]]
    assert filter_rows_by_year(rows, 2025) == rows
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_year_filter.py -v`
Expected: FAIL — `cannot import name 'extract_ids'`.

**Step 3: Implement**

```python
_TAG_RE = re.compile(r"<[^>]+>")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


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
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_year_filter.py -v`
Expected: 5 passed.

**Step 5: Verify `id_index` against real data**

The `id_index` of 0 is an assumption for every category. Confirm it with the
already-scraped files in the main checkout:

Run:
```bash
uv run python -c "
import json
for name in ['tender_2025','non_tender_2025','pencatatan_non_tender_2025']:
    rows = json.load(open(f'../../output/{name}.json', encoding='utf-8'))['data']
    print(name, rows[0][:3])
"
```

Expected: the first cell of each row is the numeric package code. If it is not,
correct `id_index` in `CATEGORIES` and add a test pinning the real value.

**Step 6: Commit**

```bash
git add spse.py tests/test_year_filter.py
git commit -m "feat: extract package ids and filter swakelola/darurat by year"
```

---

## Task 12: Phase 3 — concurrent HTML download

**Files:**
- Modify: `spse.py`
- Create: `tests/test_scrape_html.py`

**Step 1: Write the failing tests**

`tests/test_scrape_html.py`:

```python
from pathlib import Path

from spse import scrape_package_html, tab_filename


def test_tab_filename_from_url():
    assert tab_filename("https://x/kemkes/lelang/1/peserta") == "peserta.html"
    assert tab_filename("https://x/kemkes/pencatatan/pengumumannonspk?id=7") == \
        "pengumumannonspk.html"


def test_downloads_entry_tab_then_discovered_tabs(tmp_path, load_fixture):
    pages = {
        "https://x/kemkes/lelang/10158661000/pengumumanlelang": load_fixture("tender_peserta"),
        "https://x/kemkes/lelang/10158661000/peserta": load_fixture("tender_peserta"),
    }
    fetched = []

    def fake_fetch(session, url, referer, **kwargs):
        fetched.append(url)
        return pages.get(url)

    count = scrape_package_html(
        None, "https://x/kemkes", "tender", "10158661000", tmp_path,
        referer="https://x/kemkes/lelang?tahun=2025",
        fetch=fake_fetch, log=lambda *a: None,
    )
    # Entry tab plus the two tabs its nav bar advertises, deduplicated.
    assert fetched[0].endswith("/pengumumanlelang")
    assert count == 2
    assert (tmp_path / "10158661000" / "peserta.html").exists()


def test_skips_files_already_on_disk(tmp_path, load_fixture):
    target = tmp_path / "10158661000"
    target.mkdir()
    (target / "pengumumanlelang.html").write_text("x" * 500, encoding="utf-8")
    (target / "peserta.html").write_text("x" * 500, encoding="utf-8")

    def fake_fetch(session, url, referer, **kwargs):
        raise AssertionError("must not fetch when files already exist")

    count = scrape_package_html(
        None, "https://x/kemkes", "tender", "10158661000", tmp_path,
        referer="https://x", fetch=fake_fetch, log=lambda *a: None,
    )
    assert count == 0


def test_refetches_truncated_error_pages(tmp_path, load_fixture):
    target = tmp_path / "10158661000"
    target.mkdir()
    (target / "pengumumanlelang.html").write_text("403", encoding="utf-8")
    calls = []

    def fake_fetch(session, url, referer, **kwargs):
        calls.append(url)
        return load_fixture("tender_peserta")

    scrape_package_html(
        None, "https://x/kemkes", "tender", "10158661000", tmp_path,
        referer="https://x", fetch=fake_fetch, log=lambda *a: None,
    )
    assert any(url.endswith("pengumumanlelang") for url in calls)


def test_missing_entry_tab_returns_zero(tmp_path):
    count = scrape_package_html(
        None, "https://x/kemkes", "tender", "999", tmp_path, referer="https://x",
        fetch=lambda *a, **k: None, log=lambda *a: None,
    )
    assert count == 0
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scrape_html.py -v`
Expected: FAIL — `cannot import name 'scrape_package_html'`.

**Step 3: Implement**

Note the injected `fetch` parameter: it is what makes this function testable
without a network. Production callers leave it at the default.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse as _urlparse


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

    for tab in find_tabs(entry_html):
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
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_scrape_html.py -v`
Expected: 5 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_scrape_html.py
git commit -m "feat: add phase 3 concurrent html download with resume"
```

---

## Task 13: LABEL_MAP and row assembly

**Files:**
- Modify: `spse.py`
- Create: `tests/test_rows.py`

**Step 1: Write the failing tests**

`tests/test_rows.py`:

```python
import json

from spse import CSV_COLUMNS, build_rows, parse_detail


def test_core_columns_are_present_and_ordered():
    assert CSV_COLUMNS[:4] == ["slug", "nama_instansi", "kategori", "tahun"]
    assert "extra_json" == CSV_COLUMNS[-1]


def test_maps_labels_to_stable_columns(load_fixture):
    detail = parse_detail(load_fixture("tender_pemenang"))
    rows = build_rows(detail, slug="kemkes", nama_instansi="Kementerian Kesehatan",
                      kategori="tender", tahun=2025, paket_id="10102453000",
                      sumber_url="https://x")
    row = rows[0]
    assert row["nama_paket"].startswith("Paket Jasa Lainnya")
    assert row["satuan_kerja"] == "SEKRETARIAT BADAN KEBIJAKAN PEMBANGUNAN KESEHATAN"
    assert row["pagu"] == "Rp. 787.406.000,00"
    assert row["pagu_num"] == 787406000.0
    assert row["kode_paket"] == "10102453000"


def test_unmapped_labels_land_in_extra_json(load_fixture):
    detail = parse_detail(load_fixture("nontender_pengumuman"))
    rows = build_rows(detail, slug="kemkes", nama_instansi="", kategori="nontender",
                      tahun=2026, paket_id="11002302000", sumber_url="https://x")
    extra = json.loads(rows[0]["extra_json"])
    # 'Jenis Kontrak' is not promoted to a column but must not be lost.
    assert extra["Jenis Kontrak"] == "Lumsum"


def test_dates_are_normalised(load_fixture):
    detail = parse_detail(load_fixture("nontender_pengumuman"))
    rows = build_rows(detail, slug="kemkes", nama_instansi="", kategori="nontender",
                      tahun=2026, paket_id="11002302000", sumber_url="https://x")
    assert rows[0]["tanggal_pembuatan"] == "11 Agustus 2026"
    assert rows[0]["tanggal_pembuatan_iso"] == "2026-08-11"


def test_one_row_per_participant(load_fixture):
    detail = parse_detail(load_fixture("tender_peserta"))
    rows = build_rows(detail, slug="kemkes", nama_instansi="", kategori="tender",
                      tahun=2025, paket_id="10158661000", sumber_url="https://x")
    assert len(rows) == 5
    assert rows[0]["nama_pemenang"] == "Peserta 1"


def test_single_row_when_there_are_no_participants(load_fixture):
    # The package must still appear in the CSV even with an empty winner table.
    detail = parse_detail(load_fixture("tender_pemenang"))
    rows = build_rows(detail, slug="kemkes", nama_instansi="", kategori="tender",
                      tahun=2025, paket_id="10102453000", sumber_url="https://x")
    assert len(rows) == 1
    assert rows[0]["nama_pemenang"] == ""
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_rows.py -v`
Expected: FAIL — `cannot import name 'CSV_COLUMNS'`.

**Step 3: Implement**

```python
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

    extra: dict[str, str] = {}
    for label, value in detail["fields"].items():
        column = LABEL_MAP.get(label)
        if column:
            base_row[column] = value
        elif not label.endswith("[url]"):
            extra[label] = value
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

    participants = tables.get("pemenang") or tables.get("peserta")
    rows: list[dict] = []
    if participants and participants["rows"]:
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
        for column in MONEY_COLUMNS:
            row[f"{column}_num"] = parse_rupiah(row.get(column)) or ""
        for column in DATE_COLUMNS:
            row[f"{column}_iso"] = parse_tanggal(row.get(column)) or ""
        row["extra_json"] = json.dumps(extra, ensure_ascii=False) if extra else ""
    return rows
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_rows.py -v`
Expected: 6 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_rows.py
git commit -m "feat: map detail fields to csv rows with extra_json overflow"
```

---

## Task 14: Phase 4 — CSV export

**Files:**
- Modify: `spse.py`
- Create: `tests/test_export.py`

**Step 1: Write the failing tests**

`tests/test_export.py`:

```python
from pathlib import Path

from spse import export_csv


def test_writes_pipe_delimited_csv_with_header(tmp_path, load_fixture):
    packages = tmp_path / "html"
    target = packages / "10102453000"
    target.mkdir(parents=True)
    (target / "pemenangberkontrak.html").write_text(
        load_fixture("tender_pemenang"), encoding="utf-8")

    out = tmp_path / "kemkes_2025_tender.csv"
    count = export_csv(packages, out, slug="kemkes",
                       nama_instansi="Kementerian Kesehatan",
                       kategori="tender", tahun=2025,
                       base="https://spse.inaproc.id/kemkes",
                       log=lambda *a: None)
    assert count == 1
    text = out.read_text(encoding="utf-8-sig")
    header = text.splitlines()[0]
    assert header.startswith("slug|nama_instansi|kategori|tahun|")
    assert "Rp. 787.406.000,00" in text


def test_merges_all_tabs_of_one_package(tmp_path, load_fixture):
    packages = tmp_path / "html"
    target = packages / "10158661000"
    target.mkdir(parents=True)
    (target / "pengumumanlelang.html").write_text(
        load_fixture("tender_pemenang"), encoding="utf-8")
    (target / "peserta.html").write_text(
        load_fixture("tender_peserta"), encoding="utf-8")

    out = tmp_path / "out.csv"
    count = export_csv(packages, out, slug="kemkes", nama_instansi="",
                       kategori="tender", tahun=2025,
                       base="https://spse.inaproc.id/kemkes", log=lambda *a: None)
    # Fields from the pengumuman tab, five rows from the peserta table.
    assert count == 5
    text = out.read_text(encoding="utf-8-sig")
    assert "Peserta 1" in text
    assert "SEKRETARIAT BADAN KEBIJAKAN PEMBANGUNAN KESEHATAN" in text


def test_skips_directories_with_no_html(tmp_path):
    packages = tmp_path / "html"
    (packages / "empty").mkdir(parents=True)
    out = tmp_path / "out.csv"
    count = export_csv(packages, out, slug="k", nama_instansi="", kategori="tender",
                       tahun=2025, base="https://x", log=lambda *a: None)
    assert count == 0
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_export.py -v`
Expected: FAIL — `cannot import name 'export_csv'`.

**Step 3: Implement**

```python
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
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_export.py -v`
Expected: 3 passed.

**Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: all tests pass, no failures.

**Step 6: Commit**

```bash
git add spse.py tests/test_export.py
git commit -m "feat: add phase 4 csv export with optional excel conversion"
```

---

## Task 15: Run orchestration and output layout

**Files:**
- Modify: `spse.py`
- Create: `tests/test_run.py`

**Step 1: Write the failing test**

`tests/test_run.py`:

```python
from pathlib import Path

from spse import run_dir


def test_output_layout(tmp_path):
    path = run_dir("kemkes", 2025, "tender", root=tmp_path)
    assert path == tmp_path / "kemkes" / "2025" / "tender"


def test_layout_is_stable_across_categories(tmp_path):
    a = run_dir("jakarta", 2026, "swakelola", root=tmp_path)
    b = run_dir("jakarta", 2026, "darurat", root=tmp_path)
    assert a != b
    assert a.parent == b.parent
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_run.py -v`
Expected: FAIL — `cannot import name 'run_dir'`.

**Step 3: Implement**

```python
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
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_run.py -v`
Expected: 2 passed.

**Step 5: Commit**

```bash
git add spse.py tests/test_run.py
git commit -m "feat: orchestrate the four phases with a stable output layout"
```

---

## Task 16: CLI

**Files:**
- Modify: `spse.py`
- Create: `tests/test_cli.py`

**Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
import pytest

from spse import build_parser, resolve_tahun


def test_default_tahun_is_current_year():
    import datetime
    assert resolve_tahun(None) == datetime.date.today().year
    assert resolve_tahun(2019) == 2019


def test_parses_a_typical_agent_invocation():
    args = build_parser().parse_args(
        ["--agency", "jakarta", "--tipe", "tender", "--tahun", "2025"])
    assert args.agency == "jakarta"
    assert args.tipe == "tender"
    assert args.tahun == 2025


def test_rejects_an_unknown_tipe():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--agency", "x", "--tipe", "lelangan"])


def test_phase_skip_flags_default_to_running_everything():
    args = build_parser().parse_args(["--agency", "x", "--tipe", "tender"])
    assert not args.skip_json and not args.skip_html and not args.skip_csv
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `cannot import name 'build_parser'`.

**Step 3: Implement**

```python
import argparse
import datetime


def resolve_tahun(value: int | None) -> int:
    """Default the fiscal year to the current one when unspecified."""
    return int(value) if value else datetime.date.today().year


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
```

`launch_gui` does not exist yet — add a temporary stub so the module imports:

```python
def launch_gui() -> None:
    raise NotImplementedError("GUI arrives in the next task")
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 4 passed.

**Step 5: Verify the CLI works end to end without a network**

Run: `uv run python spse.py --list-agencies | head -5`
Expected: tab-separated slug and names.

Run: `uv run python spse.py --help`
Expected: usage text listing all five `--tipe` choices.

**Step 6: Commit**

```bash
git add spse.py tests/test_cli.py
git commit -m "feat: add headless cli for agent-driven runs"
```

---

## Task 17: Tkinter GUI

Not unit-tested — it is thin glue over `run_pipeline`, which is covered. It is
verified by launching it.

**Files:**
- Modify: `spse.py`

**Step 1: Replace the `launch_gui` stub**

The rule that makes this work: the worker thread never touches a Tk widget. It
pushes messages onto a queue that the main thread drains on a timer.

```python
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
    tahun_var = tk.StringVar(value=str(datetime.date.today().year))
    years = [str(y) for y in range(datetime.date.today().year, 2010, -1)]
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
```

**Step 2: Launch it**

Run: `uv run python spse.py`
Expected: a window opens. Verify by hand:
- The instansi combobox filters as you type.
- Tahun defaults to the current year.
- **Tutup** closes the window immediately.
- With Fase JSON/HTML unticked and CSV ticked, **Mulai** on an agency with no
  scraped data logs a message and finishes without crashing.

**Step 3: Confirm the test suite still passes**

Run: `uv run pytest -q`
Expected: all green (the GUI is not imported by any test).

**Step 4: Commit**

```bash
git add spse.py
git commit -m "feat: add tkinter gui with progress bar, cancel and close"
```

---

## Task 18: Live smoke test

The first and only time this plan touches the network beyond the design probes.

**Files:** none — verification only.

**Step 1: Count packages for a small agency**

Run: `uv run python spse.py --agency kemkes --tipe tender --tahun 2025 --dry`
Expected: a package count in the thousands, no traceback.

**Step 2: Scrape five packages per category**

Run each and confirm files appear under
`output/kemkes/2025/<kategori>/html/<id>/*.html`:

```bash
for tipe in tender nontender pencatatan swakelola darurat; do
  uv run python spse.py --agency kemkes --tipe $tipe --tahun 2025 --limit 5
done
```

Expected per category: `list.json` written, 5 package folders each holding 2 to 6
`.html` files, and a CSV with at least 5 rows. A `403` line for an individual
missing tab is normal and must not abort the run.

**Step 3: Confirm resume works**

Re-run one of the commands above.
Expected: `0 file baru` — every file was already complete, nothing re-downloaded.

**Step 4: Confirm offline re-export works**

Run:
```bash
uv run python spse.py --agency kemkes --tipe tender --tahun 2025 \
    --skip-json --skip-html
```
Expected: the CSV is rebuilt from disk with no network activity.

**Step 5: Inspect the CSV by eye**

Run: `uv run python -c "
import csv
rows=list(csv.DictReader(open('output/kemkes/2025/kemkes_2025_tender.csv',encoding='utf-8-sig'),delimiter='|'))
print(len(rows)); print({k:v for k,v in rows[0].items() if v})"`

Expected: populated `nama_paket`, `satuan_kerja`, `pagu`, `pagu_num`. If
`pagu_num` is blank while `pagu` has a value, `parse_rupiah` has a bug — fix it
and add a test for the failing string.

**Step 6: Commit anything you fixed**

```bash
git add -A && git commit -m "fix: corrections found during live smoke test"
```

---

## Task 19: Documentation

**Files:**
- Create: `SPSE_SCRAPER.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`

**Step 1: Write `SPSE_SCRAPER.md`**

Aimed squarely at an AI agent reading the repo cold. It must contain:

- One-paragraph statement that `spse.py` is the canonical entrypoint.
- The CLI recipes from Task 16, copy-pasteable.
- The verified endpoint and tab tables from the design document.
- The three traps: camelCase `authenticityToken`, the `recordsTotal` sentinel,
  the mandatory `Referer`.
- The `th.bgwarning` / nested-table markup contract.
- The output layout tree.
- How to add a sixth category: one entry in `CATEGORIES`, nothing else.
- A note that `output/` is gitignored and `output/all_lpse_urls.csv` must exist.

**Step 2: Add a `spse.py` section to `README.md`**

Written in Indonesian to match the rest of that file. Cover GUI usage, CLI usage,
the five `--tipe` values, and the resume behaviour. Do not delete the existing
`spse_pipeline.py` documentation.

**Step 3: Fix `CLAUDE.md`**

Two edits:
- In the endpoints table, change the Non Tender pengumuman path from
  `pengumumapl` to `pengumumanpl` — the documented slug is a typo, verified
  against the live site and `html_examples/`.
- Add `spse.py` as the canonical script, noting `spse_pipeline.py` is now legacy.

Mirror both edits into `AGENTS.md`, which duplicates this guidance.

**Step 4: Verify no emoji crept in**

Run: `uv run python -c "
import pathlib,re
for p in ['README.md','CLAUDE.md','AGENTS.md','SPSE_SCRAPER.md','spse.py']:
    t=pathlib.Path(p).read_text(encoding='utf-8')
    bad=[c for c in t if ord(c)>0x2100]
    print(p,'emoji:',bad[:5] or 'none')"`

Expected: `none` for every file. Repo rule.

**Step 5: Commit**

```bash
git add SPSE_SCRAPER.md README.md CLAUDE.md AGENTS.md
git commit -m "docs: document spse.py and fix the pengumumapl typo"
```

---

## Task 20: Final verification

**Step 1: Full suite**

Run: `uv run pytest -q`
Expected: every test passes. Record the count.

**Step 2: Confirm the single-file promise**

Run: `uv run python -c "
import ast,pathlib
tree=ast.parse(pathlib.Path('spse.py').read_text(encoding='utf-8'))
mods={n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module}
mods|={a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
print(sorted(mods))"`

Expected: stdlib plus `requests` only. `openpyxl` must appear nowhere at module
level — it is imported inside `export_excel`.

**Step 3: Confirm the GUI/CLI split**

Run: `uv run python spse.py --list-agencies | wc -l`
Expected: a count over 100, and no window opens.

**Step 4: Review the diff**

Run: `git log --oneline main..HEAD` and `git diff main --stat`
Expected: one commit per task, `spse.py` plus tests and docs, no changes to
`spse_pipeline.py` or the `scrape_*_batch.py` scripts.

**Step 5: Request review**

Use @superpowers:requesting-code-review before merging, then
@superpowers:finishing-a-development-branch to integrate.

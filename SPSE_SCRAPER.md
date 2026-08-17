# SPSE Scraper — agent reference

`spse.py` is the canonical entrypoint for scraping procurement data from
https://spse.inaproc.id. It supersedes `spse_pipeline.py` and the
`scrape_*_batch.py` scripts (which stay on disk as reference and are not
modified). One Python file drives both a Tkinter GUI (no arguments) and a
headless CLI (arguments), and exports a pipe-delimited CSV.

## CLI recipes (copy-paste)

```bash
# GUI
python spse.py

# Headless: one agency, one category, one year
python spse.py --agency jakarta --tipe tender --tahun 2025

# Count packages only (writes list.json, downloads nothing else)
python spse.py --agency jakarta --tipe tender --dry

# List all agencies as "slug<TAB>names"
python spse.py --list-agencies

# Re-export CSV from already-scraped data (no network)
python spse.py --agency jakarta --tipe tender --skip-json --skip-html

# First N packages (testing)
python spse.py --agency kemkes --tipe tender --tahun 2025 --limit 5
```

`--tipe` is one of `tender`, `nontender`, `pencatatan`, `swakelola`,
`darurat`. `--tahun` defaults to the current year when omitted. All five
categories are configurable; the default is any single category you pass.

## Endpoints and tab URLs

| Category | List endpoint | Accepts `tahun` | Entry (pengumuman) tab |
|---|---|---|---|
| Tender | `/dt/lelang?rekanan=&tahun=<y>&instansiId=` | yes | `/lelang/{id}/pengumumanlelang` |
| Non tender | `/dt/pl?tahun=<y>` | yes | `/nontender/{id}/pengumumanpl` |
| Pencatatan non tender | `/dt/nonspk?rekanan=&tahun=<y>&instansiId=` | yes | `/pencatatan/pengumumannonspk?id={id}` |
| Pencatatan swakelola | `/dt/swakelola?tahun=<y>` | yes | `/swakelola/{id}/pengumuman` |
| Pencatatan pengadaan darurat | `/dt/darurat-list?tahun=<y>` | yes | `/darurat/pengumumandarurat?id={id}` |

The entry tab is fetched first; its `ul.nav-tabs` bar reveals the package's
real tabs, which are then fetched too. Tab sets vary per package — an
unawarded tender has no `evaluasi/*` tabs at all. The nav links are rendered
as **site-root-relative** paths (`/kemkes/lelang/{id}/peserta`) on the live
site; `spse.py` resolves them against the origin with `urljoin`. A 403 or 404
on a discovered tab is logged and skipped, never fatal.

All five endpoints filter by `tahun` server-side, swakelola and darurat
included (verified live on 2026-08-17 against kemkes, jakarta, lkpp and
kemenkeu; both listing pages carry a year selector offering 2024-2027). An
earlier revision believed those two ignored `tahun` and filtered the rows in
memory instead. That was wrong twice over: it downloaded every year on every
run, and the in-memory filter matched the year anywhere in the row, so
packages merely *named* "Tahun 2026" leaked into a 2026 run (20 false
positives out of 1089 on jakarta swakelola). `filter_rows_by_year()` survives
as a dormant fallback should an endpoint ever start ignoring `tahun` again.

A category returning `0 paket` for a given year is usually just an empty year,
not a bug -- kemkes has no swakelola or darurat packages in 2026 at all, and
the site itself shows the same. Cross-check with another agency before
assuming the scraper is broken: `--agency jakarta --tipe swakelola --tahun
2026 --dry` returns 1069.

## Three traps

1. **`authenticityToken` is camelCase.** The server returns 403 for
   `authenticity_token`. A fresh token is read from each category listing page.
2. **`recordsTotal` is a sentinel.** It is hardcoded to `2147483647` (Java
   `Integer.MAX_VALUE`), never a real count. Paginate with `length=10000`,
   advance `start += len(rows)`, and stop on an empty or short page.
3. **`Referer` is mandatory on detail pages.** A warmed session still returns
   `403 Akses Ditolak!` without a `Referer` pointing at the category listing
   page. Every detail request carries it.

## Markup contract (`parse_detail`)

All five categories share one detail-page structure, so one parser serves
them all (stdlib `html.parser`, not tag-string regexes — tags carry
unpredictable attributes):

- Content root is `div#main`; the tab bar is `ul.nav-tabs` containing
  `a.nav-link[href]`, with `active` marking the current tab.
- Field rows are `<th class="bgwarning">Label</th><td colspan="N">Value</td>`.
  A row can hold more than one `th.bgwarning` (the non-tender page packs
  `Nilai Pagu Paket` and `Nilai HPS Paket` into one `<tr>`); the parser splits
  every row at each `bgwarning` cell.
- Sub-tables (Peserta, Pemenang, RUP, Realisasi, Syarat Kualifikasi) are a
  **nested `<table class="table table-sm">` inside a `<td>`** of the outer
  table, with a plain attribute-free `<th>` header row.
- `Uraian Singkat Pekerjaan` values carry links to `/{slug}/dl/<hash>`, the
  attachment PDF. The URL is captured; the file is not downloaded.

Values are cleaned: `&nbsp;` to space, `Rp. 787.406.000,00` kept raw *and* as
numeric `787406000.00`, `11 Agustus 2026` kept raw *and* as `2026-08-11`.
Both forms reach the CSV so a parse bug destroys nothing.

## Output layout

```
output/<slug>/<tahun>/
├── <slug>_<tahun>_<kategori>.csv   # pipe-delimited, UTF-8 BOM
└── <kategori>/
    ├── list.json, meta.json        # phase 2: the row list and metadata
    └── html/<id>/<tab>.html        # phase 3: one folder + file per tab
```

The CSV lands at `output/<slug>/<tahun>/<slug>_<tahun>_<kategori>.csv` (one
file per category run, not per category folder). Each package expands to one
row per participant or winner; a package with no participants still yields a
single blank-participant row. `output/` is gitignored and
`output/all_lpse_urls.csv` must exist (the agency list, 734 rows:
`name,url,old_url`, grouped by slug).

## Adding a sixth category

Add one entry to the `CATEGORIES` table in `spse.py`: `label`, `listing`,
`endpoint`, `query`, `accepts_tahun`, `columns`, `order_column`,
`entry_tab`, `id_index`. Nothing else needs editing — `parse_detail`, the
phases, the CLI, and the GUI all read from that table.
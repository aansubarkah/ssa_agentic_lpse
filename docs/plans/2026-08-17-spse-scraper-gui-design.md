# Design: `spse.py` — single-file SPSE scraper with GUI and agent CLI

Date: 2026-08-17
Status: validated, ready for implementation planning

## Goal

One Python file that scrapes https://spse.inaproc.id for any agency, year, and
procurement category, and exports a combined CSV. It must be usable two ways:

- **Human**: launch with no arguments, get a Tkinter window with dropdowns.
- **AI agent**: launch with CLI arguments, run headless, exit with a status code.

It supersedes `spse_pipeline.py` and the five untracked `scrape_*_batch.py`
scripts by absorbing their logic. Those files stay on disk as reference; they are
not modified.

## Decisions

| Question | Decision |
|---|---|
| GUI toolkit | Tkinter (stdlib) — no new dependency, one self-contained file |
| Relationship to existing scripts | New file; leave the others untouched |
| Run scope | One agency per run |
| HTML tabs | All tabs a package actually has |
| Tab URLs | Hardcode the pengumuman entry tab per category, discover the rest from `ul.nav-tabs` |
| Attachments (`/dl/<hash>` PDFs) | Not downloaded; the URL is captured into the CSV |
| Output layout | `output/<slug>/<tahun>/<kategori>/` |
| Year filter for swakelola/darurat | Endpoints ignore `tahun`; filter client-side after download |
| Export | Pipe-delimited CSV always; `.xlsx` only when requested (lazy `openpyxl` import) |
| Concurrency | `ThreadPoolExecutor`, `--workers` default 8 |
| CSV depth | Wide schema from a `LABEL_MAP`, unmapped labels preserved in `extra_json` |

## Verified facts about the site

Established by live probing and by reading the six manually saved pages in
`html_examples/`. These are the load-bearing details.

### Referer is mandatory

A warmed session with cookies still returns `403 Akses Ditolak!` on a detail page
when the `Referer` header is absent. Every detail request must send the
category's listing page as `Referer`.

### Endpoints

| Category | List endpoint | Accepts `tahun` | Entry (pengumuman) tab |
|---|---|---|---|
| Tender | `/dt/lelang?rekanan=&tahun=<y>&instansiId=` | yes | `/lelang/{id}/pengumumanlelang` |
| Non tender | `/dt/pl?tahun=<y>` | yes | `/nontender/{id}/pengumumanpl` |
| Pencatatan non tender | `/dt/nonspk?rekanan=&tahun=<y>&instansiId=` | yes | `/pencatatan/pengumumannonspk?id={id}` |
| Pencatatan swakelola | `/dt/swakelola` | no | `/swakelola/{id}/pengumuman` |
| Pencatatan pengadaan darurat | `/dt/darurat-list` | no | `/darurat/pengumumandarurat?id={id}` |

Note: `CLAUDE.md` documents the non-tender tab as `pengumumapl`. That is a typo.
The correct slug is `pengumumanpl`, confirmed live and in `html_examples/`.

Tabs observed in the wild (discovered at runtime, not hardcoded):

- Tender: `lelang/{id}/{pengumumanlelang,peserta,jadwal}`,
  `evaluasi/{id}/{hasil,pemenang,pemenangberkontrak}`
- Non tender: `nontender/{id}/{pengumumanpl,peserta,jadwal}`,
  `evaluasinontender/{id}/{hasil,pemenang,pemenangberkontrak}`
- Pencatatan non tender: `pencatatan/pengumumannonspk{,pemenang}?id={id}`
- Swakelola: `swakelola/{id}/pengumuman`,
  `swakelola/pengumumanswakelolapelaksana/{id}` (second tab is labelled
  "Pelaksana Swakelola", not "Pemenang")
- Darurat: `darurat/pengumumandarurat{,pemenang}?id={id}`

Tab sets vary per package and even between tab pages of the same package: an
unawarded tender such as `10158661000` has no `evaluasi/*` tabs at all, and
`10102453000` renders five tabs on one page and six on another. A 403 or 404 on a
discovered tab is therefore logged and skipped, never treated as fatal.

### DataTables pagination

`recordsTotal` is hardcoded to `2147483647` (Java `Integer.MAX_VALUE`) and must
be ignored. Paginate with `length=10000`, advancing `start += len(rows)`, and stop
on an empty or short page. `authenticityToken` is camelCase; the wrong form
returns 403. A fresh token is fetched per category listing page.

### HTML contract

All detail pages share one structure, so a single parser serves all five
categories:

- Content root is `div#main`; the tab bar is `ul.nav-tabs` containing
  `a.nav-link[href]` with **absolute** URLs, `active` marking the current tab.
- Field rows are `<th class="bgwarning">Label</th><td colspan="N">Value</td>`.
  `colspan` varies (2, 3, 4) between categories; the label/value rule does not.
- When a `<tr>` contains **two or more** `th.bgwarning` cells it is a horizontal
  header row, not a label/value pair. This is how the tender Pemenang Berkontrak
  table renders its six columns. The parser branches on the count.
- Sub-tables are `table.table-sm` with plain `<th width=...>` header cells.
  Realisasi tables sit inside `div.bs-callout.bs-callout-info`.

Sub-tables encountered:

| Sub-table | Columns |
|---|---|
| Rencana Umum Pengadaan | Kode RUP, Nama Paket, Sumber Dana |
| Peserta | No, Nama Peserta |
| Pemenang / Pemenang Berkontrak | Nama Pemenang, Alamat, NPWP, Harga Kontrak, Nilai PDN, Nilai UMK |
| Realisasi (swakelola, darurat) | No, Jenis Realisasi, Nilai Realisasi, Tanggal Realisasi |
| Syarat Kualifikasi (non tender) | Jenis Izin, Bidang Usaha / Sub Bidang / Klasifikasi |

Pre-award participant names are anonymised by the site (`Peserta 1`,
`Peserta 2`, ...). That is expected output, not a scrape failure.

`Uraian Singkat Pekerjaan` values contain links to `/{slug}/dl/<160-char-hash>`,
the attachment PDF. The URL is captured; the file is not downloaded.

## File structure

`spse.py` at repo root. Standard library plus `requests`; `openpyxl` imported
lazily inside the Excel branch only. Layers appear top to bottom in this order so
an agent reading the file linearly meets concepts before their uses:

1. **CONFIG** — `DELAY_S`, `PAGE_SIZE`, `MAX_RETRIES`, `MIN_FILE_SIZE`,
   `DEFAULT_WORKERS`, headers, and the `CATEGORIES` table: one dict per category
   holding its list endpoint, listing path, whether it accepts `tahun`, and its
   entry-tab URL template. All category-specific knowledge lives here; adding a
   sixth category means adding one entry, not editing functions.
2. **Agencies** — load the CSV, derive slugs, group, fuzzy-match names.
3. **HTTP** — warmed session, token extraction, retrying GET/POST with Referer.
4. **`parse_detail()`** — the generic HTML parser.
5. **Phases** — `scrape_json()`, `scrape_html()`, `export_csv()`.
6. **CLI** — argparse, headless orchestration.
7. **GUI** — Tkinter window, worker thread, queue pump.

`main()` inspects `sys.argv`: empty means GUI, otherwise headless.

```bash
python spse.py                                                  # GUI
python spse.py --agency jakarta --tipe tender --tahun 2025
python spse.py --agency jakarta --tipe tender --dry             # counts only
python spse.py --list-agencies                                  # slug + names
python spse.py --agency jakarta --tipe tender --skip-json --skip-html   # re-export offline
```

## Phases

### Phase 1 — agencies

Read `output/all_lpse_urls.csv` (734 rows, columns `name,url,old_url`). Derive
`slug` from the URL path. Group rows by slug, because many K/L share one LPSE
instance, and present one dropdown entry per slug with its member names joined.
Pure function, no network, so `--list-agencies` is instant. Agent name matching
is case-insensitive substring first, then token overlap; ambiguous matches are
reported rather than guessed.

### Phase 2 — list JSON

Warm the session on `/{slug}/{listing}?tahun=<year>`, regex out
`authenticityToken`, then POST the DataTables body with `length=10000`,
paginating until a short or empty page. Write the merged response to
`list.json`, plus a small `meta.json` recording slug, category, tahun, row
count, page size, and timestamp.

Swakelola and darurat ignore `tahun` server-side, so their `list.json` is cached
once per slug and filtered by year in memory before phase 3. The filter reads the
list row's date column, falling back to the `Tahun Anggaran` field in the
pengumuman HTML.

### Phase 3 — HTML

Per package ID: fetch the hardcoded entry tab, parse `ul.nav-tabs` for that
package's real tabs, then fetch the remainder. `ThreadPoolExecutor` fans out over
*packages*, with each package's tabs fetched sequentially inside its worker, so
the nav-discovery dependency holds. One shared warmed session (thread-safe for
GETs); every request carries the listing page as `Referer`.

Files land at `output/<slug>/<tahun>/<kategori>/<id>/<tab>.html`. An existing
file larger than `MIN_FILE_SIZE` (200 bytes) is skipped — that is the resume
mechanism, since smaller files are error pages worth re-fetching.

### Phase 4 — export

Walk the saved HTML, `parse_detail()` each tab, join to its list row, and write
one row per participant or winner.

`parse_detail(html)` returns `{"tab", "fields", "tables", "tabs"}` using stdlib
`html.parser`. Values are cleaned: `&nbsp;` to space, `Rp. 787.406.000,00` kept
raw *and* as numeric `787406000.00`, `11 Agustus 2026` kept raw *and* as
`2026-08-11`. Both forms reach the CSV so a parse bug destroys nothing. `href`s
inside a value are preserved.

Because labels differ across the five categories, a fixed column list cannot fit
them. A `LABEL_MAP` maps Indonesian labels to stable snake_case columns:

- Core: `slug, nama_instansi, kategori, tahun, kode_paket, nama_paket,
  satuan_kerja, jenis_pengadaan, metode_pengadaan, tahap, pagu, pagu_num, hps,
  hps_num, tanggal_pembuatan, kode_rup, sumber_dana, lokasi`
- Participant: `nama_pemenang, alamat, npwp, harga_kontrak, harga_kontrak_num,
  nilai_pdn, nilai_umk`
- Provenance: `sumber_url`
- Overflow: `extra_json`

Any label absent from `LABEL_MAP` is serialised into `extra_json` rather than
dropped, so an unseen SPSE field still reaches the CSV and promoting it to a real
column later is a one-line change with no re-scrape.

Output: `output/<slug>/<tahun>/<kategori>.csv`, pipe-delimited, UTF-8 with BOM.
`.xlsx` alongside it when requested.

## GUI

A single `tk.Tk` window, roughly 500x600:

```
Instansi   [ combobox with typeahead filter over 734 slugs   v ]
Tipe       [ Tender v ]        Tahun [ 2026 v ]  (default: current year)
Workers    [ 8 ]               [x] Excel juga
Fase       [x] JSON   [x] HTML   [x] CSV
           [ Mulai ]   [ Batal ]   [ Tutup ]
[==========================-------------] 412/1180 paket
[ log pane, autoscroll, monospace ]
```

The scrape runs in a `threading.Thread` that never touches Tk. It pushes
`("log", str)` and `("progress", done, total)` messages onto a `queue.Queue`
which a 100 ms `root.after` poll drains on the main thread. This keeps the window
responsive and the progress bar accurate.

- **Mulai** starts the run and disables the inputs.
- **Batal** sets a `threading.Event` the worker checks between packages. A
  cancelled run remains resumable because completed files are already on disk.
- **Tutup** cancels an active run, waits briefly, then destroys the window.

Typeahead filtering on the instansi combobox matters at 734 entries. When Tahun
is left empty the current year is used. For swakelola and darurat the year box
still applies, via the client-side filter.

## Error handling

- Per request: 3 attempts with `5 * attempt` seconds of backoff.
- 403 or 404 on a *discovered* tab: logged, skipped, not fatal.
- A package that fails all attempts is appended to `failed.json` in the run
  folder, so a re-run retries only those packages.
- Phase 2 failure aborts the run — with no IDs there is nothing to do.
- Missing `authenticityToken` raises immediately, including a response snippet.
- `DELAY_S = 0.6` between list pages is retained. With 8 workers the HTML stage
  relies on the pool for pacing rather than a per-request sleep.

## Documentation

- `README.md`: new section covering `spse.py` and its CLI recipes.
- `SPSE_SCRAPER.md`: the verified endpoint and tab tables, the Referer
  requirement, the `th.bgwarning` contract, the `recordsTotal` trap, and
  copy-paste commands aimed at AI agents.
- `CLAUDE.md`: fix the `pengumumapl` typo and point at `spse.py` as canonical.

## Testing

There is no test suite in this repo, so verification is:

- `parse_detail()` against the six files in `html_examples/` — offline, covers
  all five categories including the horizontal-header case.
- `--dry` to confirm package counts per category.
- `--limit 5` smoke run per category against a small agency.
- A resume check: interrupt a run, re-run, confirm it skips completed files.

## Out of scope

- Attachment PDF downloads (URLs captured only).
- Multi-agency and all-agency batch runs; a shell loop over `--agency` covers it.
- Parsing `jadwal` and `hasil` evaluation tables into columns. The HTML is saved,
  so parsers can be added later without re-scraping.
- Modifying `spse_pipeline.py` or the five batch scripts.

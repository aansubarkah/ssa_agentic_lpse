# AGENTS.md

SPSE scraper (Indonesia gov e-procurement). Scrapes tender/nontender/pencatatan for any agency+year → pipe-delimited CSV.

## One command to rule them all

```bash
python spse.py --agency <slug> --tipe <category> --tahun <year>
uv run python spse.py --agency kemkes --tipe tender --tahun 2025 --limit 5  # test
python spse.py  # GUI
```

## Only edit these files

| File | Role |
|---|---|
| `spse.py` | **Canonical script** — GUI + CLI, scrape + CSV, any agency/year/category |
| `spse_pipeline.py`, `scrape_*_batch.py` | **Legacy** — reference only, do not modify |
| `scrape_all.py`, `scrape_all.js`, `convert_to_csv.js` | **Legacy** — Kemkes 2025 hardcoded, touch only for old output |

Everything else is helper/config scaffolding. `main.py` is a stub.

## Environment

- **Python**: uv-managed, >=3.14, single dep `requests` (`uv sync` to install)
- **Node.js**: v22, zero runtime deps; `npm install` pulls dev-only `exceljs`
- No tests, no linter, no typechecker

## context-mode tools

context-mode is active — prefer these over inline `bash`/`cat` for large outputs. Use `uv run python` for any Python invocation.

- **Hierarchy**: `ctx_batch_execute` > `ctx_execute` > `ctx_execute_file` > `ctx_search`
- Read/edit files → `ctx_execute_file`
- Multi-command research → `ctx_batch_execute`
- Web pages → `ctx_fetch_and_index`, then `ctx_search`
- Index docs → `ctx_index`
- Stats → `ctx_stats`; doctor → `ctx_doctor`; upgrade → `ctx_upgrade`; purge → `ctx_purge`

## Critical gotchas

| Gotcha | Detail |
|---|---|
| `authenticityToken` | camelCase; server 403s on snake_case |
| Pagination | Stop on **empty page**, not `recordsTotal` (which is `Integer.MAX_VALUE`) |
| Rate limiting | 600ms delay (`DELAY_S`), page size 300 (`PAGE_SIZE`) |
| Smart resume | HTML files >200B are skipped; smaller = error page, re-fetched |
| Windows | Scripts force UTF-8 on stdout/stderr (cp1252 workaround) |
| Session | Fresh `GET` to listing page before each category for new CSRF token |

## Output layout

```
output/<agency>/<tahun>/
├── tender_<tahun>.json, non_tender_<tahun>.json, pencatatan_non_tender_<tahun>.json
├── html/{tender,non_tender,pencatatan}/{peserta|pemenang,pengumuman}/
└── <agency>_<tahun>.csv   # pipe-delimited, 28 cols, 1 row per participant
```

## CSV structure

28 pipe-delimited columns: `kategori` + JSON fields (varies by category) + 9 pengumuman + 5 peserta fields. Each package expands to N rows (one per participant).

## API endpoints

| Category | DataTables endpoint | Cols | Peserta URL | Pengumuman URL |
|---|---|---|
| Tender | `POST /<agency>/dt/lelang` | 16 | `/lelang/{kode}/peserta` | `/lelang/{kode}/pengumumanlelang` |
| Non Tender | `POST /<agency>/dt/pl` | 12 | `/nontender/{kode}/peserta` | `/nontender/{kode}/pengumumanpl` |
| Pencatatan | `POST /<agency>/dt/nonspk` | 9 | `/pencatatan/pengumumannonspkpemenang?id={kode}` | `/pencatatan/pengumumannonspk?id={kode}` |

## Command flags (`spse.py`)

`--agency` (slug or name), `--tipe` (`tender|nontender|pencatatan|swakelola|darurat`),
`--tahun`, `--limit`, `--workers`, `--excel`, `--skip-json`, `--skip-html`,
`--skip-csv`, `--dry`, `--list-agencies`

## Conventions

Never use emoji in any file or communication in this repo (especially README.md). Only use emojis if the user explicitly requests them.
